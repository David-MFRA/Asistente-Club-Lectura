from __future__ import annotations

import base64
import io
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import db

# Valores por defecto centralizados para no repartir SEO y copy publico entre
# `main.py`, `site.py` y las plantillas.
DEFAULT_CLUB_NAME = "Tribu de Libros"
DEFAULT_CITY = "Leon, Espana"
DEFAULT_HERO_TITLE = "Leemos, debatimos y crecemos."
DEFAULT_JOIN_TITLE = "Te unes al club?"
DEFAULT_JOIN_BODY = (
    "Somos un grupo de lectores apasionados. Unete, propon libros y queda con nosotros."
)
DEFAULT_PUBLIC_DESCRIPTION = (
    "Club de lectura mensual en Leon. Elegimos libros juntos, debatimos y quedamos "
    "en persona cada mes. Unete gratis y propon el proximo libro."
)
DEFAULT_GOOGLE_META_VERIFICATION = "E8RQ-2Ojv_i9bIbkgk_Pudbk2JJnSXexaJ0nCWb1l_A"
DEFAULT_GOOGLE_FILE_VERIFICATION = "google8715cced54138a71.html"


@dataclass(slots=True)
class PublicSiteSettings:
    club_name: str
    city: str
    description: str
    invite_link: str
    pub_theme: str
    hero_title: str
    section_libro: str
    section_reunion: str
    section_propuestas: str
    section_bot: str
    section_historia: str
    join_title: str
    join_body: str
    canonical_url: str
    google_meta_verification: str
    google_file_verification: str

    def to_template_context(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class PublicSiteSeoView:
    title: str
    description: str
    canonical_url: str
    qr_image_data_uri: str
    google_site_verification_token: str
    google_site_verification_file: str
    meeting_start_iso: str | None


def _string_value(source: Mapping[str, Any], key: str, default: str) -> str:
    return str(source.get(key, default) or default).strip()


def _normalize_canonical_url(raw_value: str | None, default_base_url: str) -> str:
    candidate = (raw_value or "").strip() or default_base_url.strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = "https://" + candidate.lstrip("/")
    parsed = urlsplit(candidate)
    path = (parsed.path or "").strip() or "/"
    if not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _site_root_from_canonical(canonical_url: str) -> str:
    parsed = urlsplit((canonical_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _normalise_google_file_name(raw_value: str | None) -> str:
    value = (raw_value or "").strip() or DEFAULT_GOOGLE_FILE_VERIFICATION
    if value.startswith("google-site-verification:"):
        value = value.split(":", 1)[1].strip()
    if not value.endswith(".html"):
        value = f"{value}.html"
    return value


def _meeting_start_iso(meeting: Mapping[str, Any] | None) -> str | None:
    if not meeting or not meeting.get("final_date"):
        return None
    raw_value = meeting["final_date"]
    if isinstance(raw_value, datetime):
        return raw_value.isoformat(timespec="minutes")
    text = str(raw_value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="minutes")
        except ValueError:
            continue
    return text.replace(" ", "T")


def _fallback_qr_svg_data_uri(payload: str) -> str:
    # Fallback local si la libreria de QR no esta disponible en el entorno:
    # mantiene la pagina sin dependencias remotas y deja una pista visual clara.
    safe_label = payload.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" role="img" aria-label="QR local">
  <rect width="160" height="160" fill="#ffffff"/>
  <rect x="12" y="12" width="40" height="40" fill="#07090f"/>
  <rect x="20" y="20" width="24" height="24" fill="#ffffff"/>
  <rect x="108" y="12" width="40" height="40" fill="#07090f"/>
  <rect x="116" y="20" width="24" height="24" fill="#ffffff"/>
  <rect x="12" y="108" width="40" height="40" fill="#07090f"/>
  <rect x="20" y="116" width="24" height="24" fill="#ffffff"/>
  <g fill="#07090f">
    <rect x="70" y="18" width="10" height="10"/>
    <rect x="82" y="18" width="10" height="10"/>
    <rect x="70" y="30" width="10" height="10"/>
    <rect x="94" y="30" width="10" height="10"/>
    <rect x="58" y="42" width="10" height="10"/>
    <rect x="82" y="42" width="10" height="10"/>
    <rect x="94" y="42" width="10" height="10"/>
    <rect x="58" y="66" width="10" height="10"/>
    <rect x="70" y="66" width="10" height="10"/>
    <rect x="94" y="66" width="10" height="10"/>
    <rect x="106" y="66" width="10" height="10"/>
    <rect x="58" y="78" width="10" height="10"/>
    <rect x="82" y="78" width="10" height="10"/>
    <rect x="106" y="78" width="10" height="10"/>
    <rect x="58" y="90" width="10" height="10"/>
    <rect x="70" y="90" width="10" height="10"/>
    <rect x="82" y="90" width="10" height="10"/>
    <rect x="106" y="90" width="10" height="10"/>
    <rect x="70" y="102" width="10" height="10"/>
    <rect x="94" y="102" width="10" height="10"/>
    <rect x="118" y="102" width="10" height="10"/>
    <rect x="58" y="114" width="10" height="10"/>
    <rect x="82" y="114" width="10" height="10"/>
    <rect x="94" y="114" width="10" height="10"/>
    <rect x="118" y="114" width="10" height="10"/>
  </g>
  <text
    x="80"
    y="152"
    text-anchor="middle"
    font-family="Arial, sans-serif"
    font-size="8"
    fill="#07090f"
  >QR local</text>
  <desc>{safe_label}</desc>
</svg>
""".strip()
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def build_local_qr_data_uri(payload: str) -> str:
    payload = (payload or "").strip()
    if not payload:
        return ""
    try:
        # Import diferido para no acoplar el arranque del panel a esta libreria.
        import qrcode
        from qrcode.image.svg import SvgPathImage

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        buffer = io.BytesIO()
        image.save(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
    except Exception:
        return _fallback_qr_svg_data_uri(payload)


def get_public_site_settings(
    group_invite_link: str | None,
    *,
    default_base_url: str,
) -> PublicSiteSettings:
    return PublicSiteSettings(
        club_name=db.get_config("public_club_name", DEFAULT_CLUB_NAME),
        city=db.get_config("public_city", DEFAULT_CITY),
        description=db.get_config("public_description", ""),
        invite_link=db.get_config("public_invite_link", "") or (group_invite_link or ""),
        pub_theme=db.get_config("public_theme", "amber"),
        hero_title=db.get_config("public_hero_title", DEFAULT_HERO_TITLE),
        section_libro=db.get_config("public_section_libro", "El libro que estamos leyendo"),
        section_reunion=db.get_config("public_section_reunion", "Proxima reunion"),
        section_propuestas=db.get_config("public_section_propuestas", "Propuestas en votacion"),
        section_bot=db.get_config("public_section_bot", "Como funciona el bot?"),
        section_historia=db.get_config("public_section_historia", "Lo que hemos leido juntos"),
        join_title=db.get_config("public_join_title", DEFAULT_JOIN_TITLE),
        join_body=db.get_config("public_join_body", DEFAULT_JOIN_BODY),
        canonical_url=_normalize_canonical_url(
            db.get_config("public_canonical_url", ""),
            default_base_url,
        ),
        google_meta_verification=str(
            db.get_config(
                "public_google_meta_verification",
                DEFAULT_GOOGLE_META_VERIFICATION,
            )
        ).strip(),
        google_file_verification=_normalise_google_file_name(
            db.get_config("public_google_file_verification", "")
        ),
    )


def save_public_site_settings(
    form_data: Mapping[str, Any],
    group_invite_link: str | None,
    *,
    default_base_url: str,
) -> tuple[PublicSiteSettings, PublicSiteSettings]:
    before = get_public_site_settings(group_invite_link, default_base_url=default_base_url)
    values = {
        "public_club_name": _string_value(form_data, "club_name", DEFAULT_CLUB_NAME),
        "public_city": _string_value(form_data, "city", DEFAULT_CITY),
        "public_description": str(form_data.get("description", "") or "").strip(),
        "public_invite_link": str(form_data.get("invite_link", "") or "").strip(),
        "public_theme": _string_value(form_data, "theme", "amber"),
        "public_hero_title": _string_value(form_data, "hero_title", DEFAULT_HERO_TITLE),
        "public_section_libro": _string_value(
            form_data,
            "section_libro",
            "El libro que estamos leyendo",
        ),
        "public_section_reunion": _string_value(form_data, "section_reunion", "Proxima reunion"),
        "public_section_propuestas": _string_value(
            form_data,
            "section_propuestas",
            "Propuestas en votacion",
        ),
        "public_section_bot": _string_value(form_data, "section_bot", "Como funciona el bot?"),
        "public_section_historia": _string_value(
            form_data,
            "section_historia",
            "Lo que hemos leido juntos",
        ),
        "public_join_title": _string_value(form_data, "join_title", DEFAULT_JOIN_TITLE),
        "public_join_body": _string_value(form_data, "join_body", DEFAULT_JOIN_BODY),
        "public_canonical_url": _normalize_canonical_url(
            form_data.get("canonical_url", ""),
            default_base_url,
        ),
        "public_google_meta_verification": str(
            form_data.get("google_meta_verification", "") or ""
        ).strip(),
        "public_google_file_verification": _normalise_google_file_name(
            form_data.get("google_file_verification", before.google_file_verification)
        ),
    }
    for key, value in values.items():
        db.set_config(key, value)
    after = get_public_site_settings(group_invite_link, default_base_url=default_base_url)
    return before, after


def build_public_seo_view(
    settings: PublicSiteSettings,
    *,
    winner: Mapping[str, Any] | None,
    meeting: Mapping[str, Any] | None,
) -> PublicSiteSeoView:
    city_name = settings.city.split(",")[0].strip() if settings.city else ""
    seo_title = f"{settings.club_name} - Club de lectura en {city_name or 'tu ciudad'}"
    seo_description = settings.description or DEFAULT_PUBLIC_DESCRIPTION
    return PublicSiteSeoView(
        title=seo_title,
        description=seo_description,
        canonical_url=settings.canonical_url,
        qr_image_data_uri=build_local_qr_data_uri(settings.invite_link),
        google_site_verification_token=settings.google_meta_verification,
        google_site_verification_file=settings.google_file_verification,
        meeting_start_iso=_meeting_start_iso(meeting),
    )


def build_robots_txt(*, default_base_url: str) -> str:
    settings = get_public_site_settings(None, default_base_url=default_base_url)
    site_root = _site_root_from_canonical(settings.canonical_url)
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /webhook",
    ]
    if site_root:
        lines.append(f"Sitemap: {site_root}/sitemap.xml")
    return "\n".join(lines)


def build_sitemap_xml(*, default_base_url: str) -> str:
    settings = get_public_site_settings(None, default_base_url=default_base_url)
    canonical_url = settings.canonical_url or _normalize_canonical_url("", default_base_url)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{canonical_url}</loc><changefreq>weekly</changefreq>"
        "<priority>1.0</priority></url>"
        "</urlset>"
    )


def get_google_site_verification_file(*, default_base_url: str) -> str:
    settings = get_public_site_settings(None, default_base_url=default_base_url)
    return settings.google_file_verification


def build_google_site_verification_response(*, default_base_url: str) -> str:
    file_name = get_google_site_verification_file(default_base_url=default_base_url)
    return f"google-site-verification: {file_name}"
