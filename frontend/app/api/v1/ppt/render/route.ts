import { NextRequest, NextResponse } from "next/server";
import type { PptSchema } from "@/types/ppt";
import { renderPpt } from "@/lib/ppt-renderer";

export async function POST(request: NextRequest) {
  try {
    const { schema, style } = await request.json();

    if (!schema || !Array.isArray(schema.slides)) {
      return NextResponse.json({ error: "Invalid schema" }, { status: 400 });
    }

    const buf = await renderPpt(schema as PptSchema, style || "simple");
    // base64 encode to avoid binary Response issues
    const base64 = Buffer.from(buf).toString("base64");
    return NextResponse.json({ data: base64 }, { status: 200 });
  } catch (err) {
    console.error("PPT render error:", err);
    return NextResponse.json({ error: "Render failed" }, { status: 500 });
  }
}
