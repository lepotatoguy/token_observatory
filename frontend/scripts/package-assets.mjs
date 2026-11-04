import { cp, mkdir, readdir, rm } from "node:fs/promises";
const source = new URL("../dist/", import.meta.url),
  target = new URL("../../backend/static/", import.meta.url);
await mkdir(target, { recursive: true });
for (const file of await readdir(target)) {
  if (file !== ".gitkeep")
    await rm(new URL(file, target), { recursive: true, force: true });
}
await cp(source, target, { recursive: true });
