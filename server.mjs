import http from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL(".", import.meta.url));
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
};
const publicFiles = new Set([
  "index.html",
  "styles.css",
  "src/app.js",
  "src/audio.js",
]);
http
  .createServer(async (request, response) => {
    if (!["GET", "HEAD"].includes(request.method)) {
      response.writeHead(405, { Allow: "GET, HEAD" });
      response.end();
      return;
    }
    try {
      const filename =
        decodeURIComponent(
          new URL(request.url, "http://localhost").pathname,
        ).replace(/^\/+/, "") || "index.html";
      if (!publicFiles.has(filename)) {
        response.writeHead(404);
        response.end("Not found");
        return;
      }
      const data = await readFile(path.join(root, filename));
      response.writeHead(200, {
        "Content-Type": types[path.extname(filename)],
        "Cache-Control": "no-cache",
        "X-Content-Type-Options": "nosniff",
      });
      response.end(request.method === "HEAD" ? undefined : data);
    } catch {
      response.writeHead(400);
      response.end("Bad request");
    }
  })
  .listen(Number(process.env.PORT || 3000), "0.0.0.0", () =>
    console.log(`MIXROOM listening on port ${process.env.PORT || 3000}`),
  );
