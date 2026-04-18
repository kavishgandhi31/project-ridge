/**
 * Catch-all API proxy to Hornet FastAPI backend.
 *
 * Client-side requests hit /api/proxy/scores?country_iso3=NGA
 * and this handler forwards to http://127.0.0.1:8000/scores?country_iso3=NGA.
 *
 * This keeps the FastAPI URL internal and provides a single point
 * for future auth middleware (Phase 9 Clerk integration).
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL =
  process.env.HORNET_API_URL ?? "http://127.0.0.1:8000";

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path } = await params;
  const backendPath = `/${path.join("/")}`;
  const url = new URL(backendPath, BACKEND_URL);

  // Forward query parameters
  req.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value);
  });

  try {
    const backendRes = await fetch(url.toString(), {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: req.method !== "GET" ? await req.text() : undefined,
    });

    const data = await backendRes.text();

    return new NextResponse(data, {
      status: backendRes.status,
      headers: {
        "Content-Type": "application/json",
      },
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Backend unreachable";
    return NextResponse.json(
      { error: message },
      { status: 502 }
    );
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
