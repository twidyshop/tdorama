"""Aplikasi Flask oppadrama-api."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Tuple

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from . import __version__, config, http, scraper, stream
from .http import UpstreamError
from .openapi import build_spec

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("oppadrama_api")

STATIC_DIR = "static"


def _base_path() -> str:
    """Base path saat aplikasi dipasang di belakang gateway (mis. /api/oppadrama-api)."""
    script_root = request.script_root.rstrip("/")
    return script_root or ""


def ok(data: Any, **extra: Any) -> Tuple[Response, int]:
    payload: Dict[str, Any] = {"success": True}
    payload.update(extra)
    payload["data"] = data
    return jsonify(payload), 200


def fail(message: str, status: int = 400, hint: str = None) -> Tuple[Response, int]:
    payload: Dict[str, Any] = {"success": False, "message": message}
    if hint:
        payload["hint"] = hint
    return jsonify(payload), status


def _page_arg() -> int:
    return request.args.get("page", 1)


def _multi(name: str):
    values = request.args.getlist(name)
    if not values:
        values = request.args.getlist(f"{name}[]")
    return [v for v in values if v and v.strip()]


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    CORS(app, resources={r"/*": {"origins": "*"}})
    app.config["JSON_SORT_KEYS"] = False

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    @app.get("/")
    def index():
        """Beranda web TDORAMA."""
        return send_from_directory(_static_dir(), "home.html")

    @app.get("/health")
    def health():
        info = http.upcoming_cache_info()
        return jsonify(
            {
                "success": True,
                "data": {
                    "status": "ok",
                    "version": __version__,
                    "source": config.BASE_URL,
                    "cache": info,
                },
            }
        )

    @app.get("/domains")
    def domains():
        try:
            return ok(scraper.get_domains())
        except UpstreamError as exc:
            return fail(str(exc), 502, hint="Coba lagi beberapa saat lagi.")

    @app.get("/openapi.json")
    def openapi():
        return jsonify(build_spec(_base_path()))

    @app.get("/docs")
    @app.get("/docs/")
    def docs():
        return send_from_directory(
            _static_dir(), "index.html"
        )

    @app.get("/player")
    @app.get("/player/")
    @app.get("/player.html")
    def player():
        """Halaman uji pemutaran HLS di browser."""
        return send_from_directory(_static_dir(), "player.html")

    @app.get("/docs/swagger-ui.css")
    def swagger_css():
        return send_from_directory(_static_dir(), "swagger-ui.css")

    @app.get("/docs/swagger-ui-bundle.js")
    def swagger_bundle():
        return send_from_directory(_static_dir(), "swagger-ui-bundle.js")

    @app.get("/docs/swagger-ui-standalone-preset.js")
    def swagger_preset():
        return send_from_directory(_static_dir(), "swagger-ui-standalone-preset.js")

    @app.get("/docs/swagger-ui-init.js")
    def swagger_init():
        spec = build_spec(_base_path())
        js = (
            "window.onload = function() {\n"
            f"  const spec = {_json_dumps(spec)};\n"
            "  window.ui = SwaggerUIBundle({\n"
            "    spec: spec,\n"
            "    dom_id: '#swagger-ui',\n"
            "    deepLinking: true,\n"
            "    presets: [SwaggerUIBundle.presets.apis, "
            "SwaggerUIStandalonePreset],\n"
            "    plugins: [SwaggerUIBundle.plugins.DownloadUrl],\n"
            "    layout: 'StandaloneLayout'\n"
            "  });\n"
            "};\n"
        )
        return Response(js, mimetype="application/javascript")

    # ------------------------------------------------------------------
    # Konten
    # ------------------------------------------------------------------

    @app.get("/home")
    def home():
        try:
            return ok(scraper.get_home(_page_arg()))
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    @app.get("/home/<section>")
    def home_section(section: str):
        aliases = {
            "ongoing": "Sedang Tayang",
            "recommendation": "Rekomendasi",
            "recommendations": "Rekomendasi",
            "newseries": "Judul Drama/Series Baru",
            "latest": "Rilisan Terbaru",
        }
        want = aliases.get((section or "").strip().lower())
        if not want:
            return fail(
                "Section tidak dikenal.",
                400,
                hint="Pilihan: " + ", ".join(sorted(set(aliases))),
            )
        try:
            data = scraper.get_home(_page_arg())
            for sec in data.get("sections", []):
                if (sec.get("title") or "").strip().lower() == want.lower():
                    return ok(sec, title=sec.get("title"))
            return fail(f"Section '{want}' tidak ditemukan di beranda.", 404)
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    @app.get("/series")
    def series_list():
        try:
            data = scraper.get_series(
                _page_arg(),
                status=request.args.get("status"),
                type_=request.args.get("type"),
                order=request.args.get("order"),
                genre=_multi("genre"),
                country=_multi("country"),
                season=_multi("season"),
                studio=_multi("studio"),
                network=_multi("network"),
            )
            return ok(data)
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    @app.get("/series/filters")
    def series_filters():
        try:
            return ok(scraper.get_filter_options())
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    @app.get("/series/latest")
    def series_latest():
        try:
            return ok(scraper.get_recent_episodes(_page_arg()))
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    @app.get("/series/list")
    def series_list_mode():
        try:
            return ok(scraper.get_list_mode(_page_arg()))
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    @app.get("/series/<slug>")
    def series_detail(slug: str):
        try:
            return ok(scraper.get_series_detail(slug))
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            status = getattr(exc, "status", 502)
            if status == 404:
                return fail("Series tidak ditemukan", 404)
            return fail(str(exc), status)

    @app.get("/series/<slug>/episodes")
    def series_episodes(slug: str):
        try:
            return ok(scraper.get_series_episodes(slug))
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            status = getattr(exc, "status", 502)
            if status == 404:
                return fail("Series tidak ditemukan", 404)
            return fail(str(exc), status)

    @app.get("/episode/<slug>")
    def episode_detail(slug: str):
        try:
            data = scraper.get_episode_detail(slug)
            base = _base_path()
            for m in data.get("mirrors", []):
                if m.get("embed"):
                    m["streamEndpoint"] = (
                        f"{base}/stream?url={m['embed']}"
                    )
            if data.get("defaultEmbed"):
                data["streamEndpoint"] = (
                    f"{base}/episode/{data.get('slug')}/stream"
                )
            return ok(data)
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            status = getattr(exc, "status", 502)
            if status == 404:
                return fail("Episode tidak ditemukan", 404)
            return fail(str(exc), status)

    @app.get("/episode/<slug>/stream")
    def episode_stream(slug: str):
        try:
            detail = scraper.get_episode_detail(slug)
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            status = getattr(exc, "status", 502)
            if status == 404:
                return fail("Episode tidak ditemukan", 404)
            return fail(str(exc), status)

        mirrors = [m for m in detail.get("mirrors", []) if m.get("embed")]
        if not mirrors:
            return fail(
                "Tidak ada server streaming untuk episode ini.",
                404,
                hint="Coba /episode/<slug> untuk melihat server yang tersedia.",
            )

        server_index = request.args.get("server")
        chosen = mirrors[0]
        if server_index:
            try:
                idx = int(server_index)
            except ValueError:
                return fail("Parameter 'server' harus berupa angka", 400)
            match = [m for m in mirrors if m.get("index") == idx]
            if not match:
                if 1 <= idx <= len(mirrors):
                    match = [mirrors[idx - 1]]
                else:
                    return fail(
                        f"Server index {idx} tidak ada (tersedia 1..{len(mirrors)})",
                        400,
                    )
            chosen = match[0]

        try:
            data = stream.resolve_full(chosen["embed"], proxy_base=_base_path())
        except ValueError as exc:
            return fail(str(exc), 400, hint="Server mungkin bukan penyedia yang didukung.")
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

        data["episode"] = {
            "title": detail.get("title"),
            "slug": detail.get("slug"),
            "url": detail.get("url"),
        }
        data["server"] = {
            "name": chosen.get("name"),
            "host": chosen.get("host"),
            "index": chosen.get("index"),
            "total": len(mirrors),
        }
        data["servers"] = [
            {"name": m.get("name"), "host": m.get("host"), "index": m.get("index")}
            for m in mirrors
        ]
        data["downloads"] = detail.get("downloads", [])
        return ok(data)

    @app.get("/stream")
    def stream_info():
        target = request.args.get("url") or request.args.get("embed")
        try:
            data = stream.resolve_full(target or "", proxy_base=_base_path())
            return ok(data)
        except ValueError as exc:
            return fail(
                str(exc),
                400,
                hint="Contoh: /stream?url=https://vidara.to/e/XXXXXXXX",
            )
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    @app.get("/stream/playlist")
    def stream_playlist():
        url = request.args.get("u")
        if not url:
            return fail("Parameter 'u' wajib diisi", 400)
        referer = request.args.get("r") or stream.VIDARA_REFERER
        raw = request.args.get("raw") == "1"
        try:
            text = stream.fetch_playlist(url, referer=referer)
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

        body = text if raw else stream.rewrite_m3u8(
            url, text, proxy_base=_base_path(), referer=referer
        )
        resp = Response(body, mimetype="application/vnd.apple.mpegurl")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/stream/seg")
    def stream_segment():
        url = request.args.get("u")
        if not url:
            return fail("Parameter 'u' wajib diisi", 400)
        referer = request.args.get("r") or stream.VIDARA_REFERER
        try:
            upstream = stream.proxy_segment(
                url,
                referer=referer,
                range_header=request.headers.get("Range"),
            )
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=config.SEGMENT_CHUNK):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        status = upstream.status_code
        resp = Response(
            generate(),
            status=status,
            mimetype=stream.guess_segment_type(
                url, upstream.headers.get("Content-Type")
            ),
        )
        for header in (
            "Content-Length",
            "Content-Range",
            "Accept-Ranges",
            "ETag",
            "Last-Modified",
        ):
            value = upstream.headers.get(header)
            if value:
                resp.headers[header] = value
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Range"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Length,Content-Range"
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    @app.get("/search")
    def search():
        query = request.args.get("q") or request.args.get("query")
        try:
            return ok(scraper.search(query or "", _page_arg()))
        except ValueError as exc:
            return fail(str(exc), 400, hint="Contoh: /search?q=deception")
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    # ------------------------------------------------------------------
    # Taksonomi
    # ------------------------------------------------------------------

    @app.get("/genres")
    def genres():
        try:
            html = http.get_text(f"{config.BASE_URL}/series/")
            terms = _flatten_filter_terms(html, "genre[]")
            return ok({"total": len(terms), "genres": terms})
        except UpstreamError as exc:
            return fail(str(exc), getattr(exc, "status", 502))

    def _taxonomy(kind: str, slug: str):
        try:
            return ok(scraper.get_taxonomy_archive(kind, slug, _page_arg()))
        except ValueError as exc:
            return fail(str(exc), 400)
        except UpstreamError as exc:
            status = getattr(exc, "status", 502)
            if status == 404:
                return fail(f"{kind.capitalize()} tidak ditemukan", 404)
            return fail(str(exc), status)

    @app.get("/genre/<slug>")
    def genre_archive(slug: str):
        return _taxonomy("genre", slug)

    @app.get("/country/<slug>")
    def country_archive(slug: str):
        return _taxonomy("country", slug)

    @app.get("/cast/<slug>")
    def cast_archive(slug: str):
        return _taxonomy("cast", slug)

    @app.get("/director/<slug>")
    def director_archive(slug: str):
        return _taxonomy("director", slug)

    @app.get("/tag/<slug>")
    def tag_archive(slug: str):
        return _taxonomy("tag", slug)

    @app.get("/network/<slug>")
    def network_archive(slug: str):
        return _taxonomy("network", slug)

    @app.get("/season/<slug>")
    def season_archive(slug: str):
        return _taxonomy("season", slug)

    @app.get("/studio/<slug>")
    def studio_archive(slug: str):
        return _taxonomy("studio", slug)

    # ------------------------------------------------------------------
    # Error handler
    # ------------------------------------------------------------------

    @app.errorhandler(UpstreamError)
    def upstream_error(error):
        status = getattr(error, "status", 502)
        if status not in (400, 404, 422, 500, 502, 503):
            status = 502
        return fail(str(error), status)

    @app.errorhandler(404)
    def not_found(error):
        base = _base_path()
        return fail(
            f"Route tidak ditemukan: {request.method} {request.path}",
            404,
            hint=(
                f"Coba {base}/home atau lihat daftar endpoint di {base}/ "
                f"dan dokumentasi di {base}/docs"
            ),
        )

    @app.errorhandler(405)
    def method_not_allowed(error):
        return fail(f"Method {request.method} tidak diizinkan", 405)

    @app.errorhandler(500)
    def internal_error(error):
        logger.exception("Kesalahan internal")
        return fail("Internal server error", 500)

    return app


def _flatten_filter_terms(html: str, name: str):
    from . import parsers

    options = parsers.parse_filter_options(html)
    return [
        {"name": item["name"], "slug": item["slug"]}
        for item in options.get(name, [])
    ]


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _static_dir() -> str:
    import os

    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), STATIC_DIR)


app = create_app()


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "5000"))
    logger.info("Menjalankan oppadrama-api di port %s", port)
    app.run(debug=True, host="0.0.0.0", port=port)
