"""Numérisation : photos de pages (téléphone, webcam, tablette) -> un seul PDF « scanné ».

Pour chaque page :
  1. orientation EXIF appliquée, puis redressement de perspective d'après les 4 coins
     de la feuille (détectés ou ajustés dans le navigateur) ;
  2. rotation demandée (0, 90, 180, 270°) ;
  3. amélioration selon le mode :
       * document : niveaux de gris, ombres et fond gris supprimés, contraste renforcé
                    (meilleur rendu et meilleur OCR pour du texte) ;
       * gris     : niveaux de gris avec contraste automatique ;
       * couleur  : couleurs conservées, contraste automatique léger ;
  4. réduction à 300 ppp au format A4 au plus (taille de fichier maîtrisée).
Les pages sont assemblées en un PDF qui suit ensuite le circuit normal :
empreinte SHA-256, chiffrement, OCR et conversion PDF/A.
"""
import hashlib
import io
import math
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageFilter, ImageOps, UnidentifiedImageError

from app.services.documents import BusinessError

MODES = ("document", "gris", "couleur")
MAX_PAGES = 60
MAX_PAGE_BYTES = 25 * 1024 * 1024
MAX_SIDE = 3508          # A4 à 300 ppp (côté long)
A4_LONG_INCH = 11.69


@dataclass
class PageOptions:
    corners: list[list[float]] | None = None   # 4 points [x, y] normalisés (0..1), dans l'ordre HG, HD, BD, BG
    rotation: int = 0


@dataclass
class ScanResult:
    pdf: bytes
    pages: int
    page_hashes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ Géométrie
def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Élimination de Gauss avec pivot partiel (système 8x8, sans dépendance)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            raise BusinessError("Coins de la page incohérents (points alignés)", 422)
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def perspective_coeffs(dst_size: tuple[int, int], src_pts: list[tuple[float, float]]) -> list[float]:
    """Coefficients PIL PERSPECTIVE : pour chaque pixel (x, y) du résultat, point source correspondant."""
    w, h = dst_size
    dst = [(0, 0), (w, 0), (w, h), (0, h)]
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src_pts):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return _solve(a, b)


def _validate_corners(corners) -> list[tuple[float, float]] | None:
    if corners is None:
        return None
    if (not isinstance(corners, list) or len(corners) != 4
            or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in corners)):
        raise BusinessError("Coins : 4 points [x, y] attendus", 422)
    pts = []
    for x, y in corners:
        if not all(isinstance(c, (int, float)) and math.isfinite(c) for c in (x, y)):
            raise BusinessError("Coins : valeurs numériques attendues", 422)
        pts.append((min(max(float(x), 0.0), 1.0), min(max(float(y), 0.0), 1.0)))
    # Quadrilatère convexe orienté dans le sens horaire (produit vectoriel de même signe)
    signs = set()
    for i in range(4):
        (x1, y1), (x2, y2), (x3, y3) = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        cross = (x2 - x1) * (y3 - y2) - (y2 - y1) * (x3 - x2)
        if abs(cross) < 1e-6:
            raise BusinessError("Coins de la page incohérents (points alignés)", 422)
        signs.add(cross > 0)
    if len(signs) != 1:
        raise BusinessError("Coins de la page incohérents (forme croisée)", 422)
    return pts


def warp(img: Image.Image, corners: list[tuple[float, float]]) -> Image.Image:
    w, h = img.size
    src = [(x * w, y * h) for x, y in corners]
    dist = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1])  # noqa: E731
    out_w = int(max(dist(src[0], src[1]), dist(src[3], src[2])))
    out_h = int(max(dist(src[0], src[3]), dist(src[1], src[2])))
    if out_w < 50 or out_h < 50:
        raise BusinessError("Zone de page trop petite", 422)
    out = img.transform((out_w, out_h), Image.Transform.PERSPECTIVE,
                        perspective_coeffs((out_w, out_h), src), Image.Resampling.BICUBIC)
    m = max(2, min(out_w, out_h) // 200)  # rogne le liseré du bord de la feuille
    return out.crop((m, m, out_w - m, out_h - m))


# ------------------------------------------------------------------ Amélioration
def enhance(img: Image.Image, mode: str) -> Image.Image:
    if mode == "couleur":
        return ImageOps.autocontrast(img.convert("RGB"), cutoff=0.5)
    gray = img.convert("L")
    if mode == "gris":
        return ImageOps.autocontrast(gray, cutoff=1)
    # Mode document : on estime le fond (papier + ombres) par un flou large, puis on garde
    # l'écart à ce fond -> fond blanc uniforme, texte sombre, ombres de la main effacées.
    small = gray.resize((max(1, gray.width // 8), max(1, gray.height // 8)))
    background = small.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(6)).resize(gray.size)
    ink = ImageChops.subtract(background, gray)               # 0 = papier, >0 = encre
    clean = ImageOps.invert(ImageOps.autocontrast(ink, cutoff=(0, 0.5)))
    return clean.point(lambda p: 255 if p > 235 else int(p * 0.9))  # blanchit le fond, densifie l'encre


def _fit(img: Image.Image) -> Image.Image:
    if max(img.size) > MAX_SIDE:
        img = img.copy()
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return img


# ------------------------------------------------------------------ Assemblage
def process_page(raw: bytes, opts: PageOptions, mode: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise BusinessError("Image illisible : formats acceptés JPEG, PNG, WebP ou TIFF", 422) from exc
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    corners = _validate_corners(opts.corners)
    if corners:
        img = warp(img, corners)
    if opts.rotation % 360:
        if opts.rotation % 90:
            raise BusinessError("Rotation : 0, 90, 180 ou 270 degrés", 422)
        img = img.rotate(-opts.rotation, expand=True)   # sens horaire
    return _fit(enhance(img, mode))


def build_pdf(pages: list[bytes], options: list[PageOptions], mode: str = "document") -> ScanResult:
    if mode not in MODES:
        raise BusinessError("Mode : document, gris ou couleur", 422)
    if not pages:
        raise BusinessError("Aucune page à numériser", 422)
    if len(pages) > MAX_PAGES:
        raise BusinessError(f"Trop de pages (maximum {MAX_PAGES})", 422)
    options = (options + [PageOptions()] * len(pages))[:len(pages)]
    images, hashes = [], []
    for raw, opts in zip(pages, options):
        if len(raw) > MAX_PAGE_BYTES:
            raise BusinessError("Photo trop volumineuse (25 Mo maximum par page)", 413)
        hashes.append(hashlib.sha256(raw).hexdigest())
        images.append(process_page(raw, opts, mode))
    buf = io.BytesIO()
    # Résolution choisie pour que la page la plus longue corresponde à une feuille A4
    dpi = max(72.0, min(600.0, max(images[0].size) / A4_LONG_INCH))
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:], resolution=dpi,
                   title="Document numérisé", producer="GEDarchive", quality=85)
    return ScanResult(buf.getvalue(), len(images), hashes)
