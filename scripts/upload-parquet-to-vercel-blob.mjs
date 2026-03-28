#!/usr/bin/env node
/**
 * Upload pipeline Parquet files under data/output/ to Vercel Blob.
 *
 * Prerequisite (one-time): In the Vercel dashboard → Storage → Create Blob store,
 * link it to your project, then copy the read-write token or run `vercel env pull`.
 *
 * Usage:
 *   Put BLOB_READ_WRITE_TOKEN in repo-root .env.local (or .env), then:
 *     npm run upload:blob
 *   Or: export BLOB_READ_WRITE_TOKEN="vercel_blob_..." npm run upload:blob
 *
 * Options:
 *   --root <dir>     Local folder to scan (default: <repo>/data/output)
 *   --prefix <path>  Blob pathname prefix, no leading slash (default: output)
 *   --dry-run        List files only
 *   --private        Use access: private (default: public, easier for plain HTTP GET)
 *
 * Env:
 *   BLOB_READ_WRITE_TOKEN  Required
 *   BLOB_ACCESS            public | private (overridden by --private)
 */

import { put } from "@vercel/blob";
import { createReadStream, existsSync, readFileSync } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

const MULTIPART_MIN_BYTES = 4_500_000;

/** Parse KEY=VAL lines from a file (returns a plain object). */
function parseEnvFile(fp) {
  const out = {};
  if (!existsSync(fp)) return out;
  const text = readFileSync(fp, "utf8");
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("=");
    if (eq <= 0) continue;
    const key = t.slice(0, eq).trim();
    let val = t.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    out[key] = val;
  }
  return out;
}

/** Merge repo-root .env then .env.local; only fills keys missing from process.env (shell wins). */
function loadRepoEnvFiles() {
  const merged = {
    ...parseEnvFile(path.join(REPO_ROOT, ".env")),
    ...parseEnvFile(path.join(REPO_ROOT, ".env.local")),
  };
  for (const [key, val] of Object.entries(merged)) {
    if (process.env[key] === undefined) process.env[key] = val;
  }
}

loadRepoEnvFiles();

function parseArgs(argv) {
  let root = path.join(REPO_ROOT, "data", "output");
  let prefix = "output";
  let dryRun = false;
  let access = process.env.BLOB_ACCESS === "private" ? "private" : "public";

  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--dry-run") dryRun = true;
    else if (a === "--private") access = "private";
    else if (a === "--root" && argv[i + 1]) {
      root = path.resolve(argv[++i]);
    } else if (a === "--prefix" && argv[i + 1]) {
      prefix = argv[++i].replace(/^\/+|\/+$/g, "");
    } else if (a === "--help" || a === "-h") {
      console.log(`
upload-parquet-to-vercel-blob.mjs

  --root <dir>      Scan this directory recursively (default: data/output)
  --prefix <path>   Blob key prefix (default: output)
  --dry-run         Print paths only
  --private         Upload as private blobs
`);
      process.exit(0);
    }
  }
  return { root, prefix, dryRun, access };
}

async function* walkParquetFiles(dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (e) {
    if (e.code === "ENOENT") {
      console.error(`Directory does not exist: ${dir}`);
      return;
    }
    throw e;
  }
  for (const ent of entries) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      yield* walkParquetFiles(full);
    } else if (ent.isFile() && ent.name.endsWith(".parquet")) {
      yield full;
    }
  }
}

async function main() {
  const { root, prefix, dryRun, access } = parseArgs(process.argv);

  if (!dryRun && !process.env.BLOB_READ_WRITE_TOKEN) {
    console.error(
      "Missing BLOB_READ_WRITE_TOKEN. Create a Blob store in Vercel → Storage, then set the token."
    );
    process.exit(1);
  }

  console.log(`Scanning: ${root}`);
  console.log(`Blob prefix: ${prefix}/`);
  console.log(`Access: ${access}`);
  if (dryRun) console.log("(dry-run)\n");

  const uploaded = [];
  for await (const absPath of walkParquetFiles(root)) {
    const rel = path.relative(root, absPath);
    const blobPath = `${prefix}/${rel.split(path.sep).join("/")}`;

    if (dryRun) {
      console.log(`  ${blobPath}`);
      continue;
    }

    const st = await stat(absPath);
    const stream = createReadStream(absPath);
    const result = await put(blobPath, stream, {
      access,
      allowOverwrite: true,
      addRandomSuffix: false,
      contentType: "application/vnd.apache.parquet",
      multipart: st.size >= MULTIPART_MIN_BYTES,
    });
    uploaded.push({ pathname: blobPath, url: result.url });
    console.log(`  OK ${blobPath} (${(st.size / 1e6).toFixed(2)} MB)`);
  }

  if (!dryRun && uploaded.length === 0) {
    console.warn("No .parquet files found. Run the pipeline or fix --root.");
    process.exit(1);
  }

  if (!dryRun) {
    console.log(`\nUploaded ${uploaded.length} file(s).`);
  }
}

main().catch((err) => {
  console.error(err);
  const msg = String(err?.message ?? err);
  if (msg.includes("private store") && msg.includes("public")) {
    console.error(`
Your Blob store is a Private store. You cannot upload with access: public.

  • Use private uploads (works with your current store):
      npm run upload:blob:private
    or: BLOB_ACCESS=private npm run upload:blob

  • Or create a new Public Blob store: Vercel → project → Storage → Create → Blob → set access to Public,
    then point BLOB_READ_WRITE_TOKEN at that store (vercel env pull).
`);
  }
  process.exit(1);
});
