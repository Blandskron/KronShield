// Local, synthetic landing server for production-build Lighthouse audits.
import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createGzip } from "node:zlib";

const dist = fileURLToPath(new URL("../dist", import.meta.url));
const mime = {
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

createServer((request, response) => {
  const path = request.url?.split("?", 1)[0] ?? "";
  if (request.method !== "GET") {
    response.writeHead(405).end();
  } else if (path === "/api/v1/me") {
    response.writeHead(401, { "Content-Type": "application/json" }).end('{"code":"authentication_required"}');
  } else if (path === "/api/v1/auth/mode") {
    response.writeHead(200, { "Content-Type": "application/json" }).end('{"mode":"pilot"}');
  } else if (path === "/" || /^\/assets\/[a-z0-9][a-z0-9_.-]+$/i.test(path)) {
    const filename = join(dist, path === "/" ? "index.html" : path.slice(1));
    const content = createReadStream(filename);
    content.on("open", () => {
      const extension = extname(filename);
      const compress = extension !== ".woff2" && request.headers["accept-encoding"]?.includes("gzip");
      response.writeHead(200, {
        "Content-Type": mime[extension] ?? "application/octet-stream",
        Vary: "Accept-Encoding",
        ...(compress ? { "Content-Encoding": "gzip" } : {}),
      });
      if (compress) content.pipe(createGzip()).pipe(response);
      else content.pipe(response);
    });
    content.on("error", () => response.writeHead(404).end());
  } else {
    response.writeHead(404).end();
  }
}).listen(4179, "127.0.0.1");
