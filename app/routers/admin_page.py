"""HTML-rendered admin routes."""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import get_user_by_token, require_token
from ..models import User

admin_page_router = APIRouter(tags=["admin"])


@admin_page_router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_login_page(error: str | None = Query(default=None)) -> HTMLResponse:
    """Render the admin login form."""

    error_block = ""
    if error == "invalid":
        error_block = (
            "<p class=\"error\">Invalid token. Please try again.</p>"
        )
    html = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\">
        <title>Admin Access</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            background: #f7f7f7;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
          }}
          .container {{
            background: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 360px;
            text-align: center;
          }}
          h1 {{
            font-size: 1.4rem;
            margin-bottom: 1.5rem;
          }}
          form {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
          }}
          input[type="text"] {{
            padding: 0.75rem;
            font-size: 1rem;
            border: 1px solid #ccc;
            border-radius: 4px;
          }}
          button {{
            padding: 0.75rem;
            font-size: 1rem;
            background: #3d6c6f;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
          }}
          button:hover {{
            background: #335759;
          }}
          .error {{
            color: #b00020;
            margin-bottom: 1rem;
          }}
        </style>
      </head>
      <body>
        <div class=\"container\">
          <h1>Admin Access</h1>
          {error_block}
          <form method=\"post\" action=\"/admin/login\">
            <input type=\"text\" name=\"token\" placeholder=\"Enter access token\" required>
            <button type=\"submit\">Enter</button>
          </form>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@admin_page_router.post("/admin/login", include_in_schema=False)
def admin_login(token: str = Form(...)) -> RedirectResponse:
    """Validate the provided token and redirect accordingly."""

    normalized_token = token.strip()
    if not get_user_by_token(normalized_token):
        return RedirectResponse(
            url="/admin?error=invalid",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    redirect_url = f"/admin/dashboard?t={quote_plus(normalized_token)}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@admin_page_router.get(
    "/admin/dashboard",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def admin_dashboard(user: User = Depends(require_token)) -> HTMLResponse:
    """Render the admin dashboard placeholder page."""

    html = """
    <!DOCTYPE html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\">
        <title>Admin Dashboard</title>
        <style>
          body {
            font-family: Arial, sans-serif;
            background: #f3f5f7;
            color: #1a1a1a;
            margin: 0;
            padding: 0;
          }
          .wrapper {
            max-width: 720px;
            margin: 4rem auto;
            background: white;
            padding: 2.5rem;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
          }
          h1 {
            margin-top: 0;
            color: #2c585b;
          }
          p {
            line-height: 1.6;
          }
          a.logout {
            display: inline-block;
            margin-top: 2rem;
            color: #2c585b;
            text-decoration: none;
            font-weight: 600;
          }
          a.logout:hover {
            text-decoration: underline;
          }
        </style>
      </head>
      <body>
        <div class=\"wrapper\">
          <h2>Welcome to the Auto-Generator Console</h2>
          <p>Token verified. You can proceed with admin operations.</p>
          <a class=\"logout\" href=\"/admin\">Logout</a>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
