import type { APIRoute } from "astro";

// Switches the signed-in browser session between an owner and the profiles
// they manage (see backend/routers/profiles.py). The login token lives in an
// httpOnly cookie, so the swap has to happen server side.
//   POST profile_id=<id>  -> sign in as that managed profile
//   POST back=1           -> return to the owner's own account
const BACKEND_PORT = (import.meta.env.BACKEND_PORT as string | undefined) ?? "7331";
const BACKEND = `http://localhost:${BACKEND_PORT}`;
const OWNER_COOKIE = "owner_token";
const WEEK = 60 * 60 * 24 * 7;

export const POST: APIRoute = async ({ request, cookies, url, redirect }) => {
  // Same-origin only: this endpoint replaces the login cookie.
  const origin = request.headers.get("Origin");
  if (origin) {
    let originHost = "";
    try {
      originHost = new URL(origin).host;
    } catch {
      return new Response("Forbidden", { status: 403 });
    }
    const ownHost = request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? url.host;
    if (originHost !== ownHost) return new Response("Forbidden", { status: 403 });
  }

  const secure = url.protocol === "https:" || request.headers.get("x-forwarded-proto") === "https";
  const cookieOpts = { path: "/", httpOnly: true, sameSite: "lax" as const, secure };
  const form = await request.formData();
  const current = cookies.get("token")?.value;
  const owner = cookies.get(OWNER_COOKIE)?.value;

  if (form.get("back") !== null) {
    if (owner) {
      cookies.set("token", owner, { ...cookieOpts, maxAge: WEEK });
      cookies.delete(OWNER_COOKIE, { path: "/" });
    }
    return redirect("/", 303);
  }

  const id = Number(form.get("profile_id"));
  if (!Number.isInteger(id) || id <= 0) return new Response("Bad request", { status: 400 });

  // While viewing a profile the owner's token is parked in OWNER_COOKIE, so
  // switching straight to another profile works.
  const ownerToken = owner ?? current;
  if (!ownerToken) return redirect("/login", 303);

  let res: Response;
  try {
    res = await fetch(`${BACKEND}/profiles/${id}/switch`, {
      method: "POST",
      headers: { Authorization: `Bearer ${ownerToken}` },
    });
  } catch {
    return new Response("Backend unavailable", { status: 502 });
  }
  if (!res.ok) return new Response("Could not switch profile", { status: res.status === 401 ? 401 : 400 });

  const data = (await res.json()) as { access_token: string; expires_in: number };
  cookies.set(OWNER_COOKIE, ownerToken, { ...cookieOpts, maxAge: WEEK });
  cookies.set("token", data.access_token, { ...cookieOpts, maxAge: data.expires_in });
  return redirect("/", 303);
};
