import { NextResponse } from "next/server";

export function proxy() {
  // The layout's notFound can stream an HTTP 200. Reject production requests
  // before the app shell starts streaming.
  if (process.env.NODE_ENV === "production") {
    return new Response("Not found", { status: 404 });
  }
  return NextResponse.next();
}

export const config = { matcher: "/sandbox/:path*" };
