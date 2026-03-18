from __future__ import annotations

from flask import Response, abort

from app.services.public_site import (
    build_google_site_verification_response,
    build_robots_txt,
    build_sitemap_xml,
    get_google_site_verification_file,
)


def install_public_site_routes(flask_app, *, webhook_url: str):
    """Registra las rutas publicas y de SEO compartidas por toda la aplicacion."""

    @flask_app.get("/robots.txt")
    def robots_txt():
        return Response(
            build_robots_txt(default_base_url=webhook_url),
            mimetype="text/plain",
        )

    @flask_app.get("/sitemap.xml")
    @flask_app.get("/publico/sitemap.xml")
    def sitemap_xml():
        return Response(
            build_sitemap_xml(default_base_url=webhook_url),
            mimetype="application/xml",
        )

    @flask_app.get("/google8715cced54138a71.html")
    @flask_app.get("/publico/google8715cced54138a71.html")
    def google_site_verification():
        # Se conserva la ruta historica por compatibilidad con Search Console.
        return Response(
            build_google_site_verification_response(default_base_url=webhook_url),
            mimetype="text/html",
        )

    @flask_app.get("/google<token>.html")
    @flask_app.get("/publico/google<token>.html")
    def google_site_verification_dynamic(token: str):
        # La ruta se valida contra la configuracion actual para que un cambio
        # posterior desde admin no obligue a reiniciar el servidor.
        expected_file = get_google_site_verification_file(default_base_url=webhook_url)
        requested_file = f"google{token}.html"
        if requested_file != expected_file:
            abort(404)
        return Response(
            build_google_site_verification_response(default_base_url=webhook_url),
            mimetype="text/html",
        )

    @flask_app.get("/favicon.ico")
    def favicon():
        return Response(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<rect width="100" height="100" rx="18" fill="#101828"/>'
                '<text x="50" y="62" font-size="34" text-anchor="middle" fill="#f8fafc" '
                'font-family="Arial, sans-serif">CL</text>'
                "</svg>"
            ),
            mimetype="image/svg+xml",
        )

    @flask_app.get("/health")
    def health():
        return {"status": "running"}, 200
