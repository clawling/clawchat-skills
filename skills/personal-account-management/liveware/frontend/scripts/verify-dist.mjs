import { spawnSync } from "node:child_process";
import { mkdtemp, readdir, readFile, rm, lstat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const committedDist = path.resolve(frontendDir, "../dist");
const temporaryDist = await mkdtemp(path.join(tmpdir(), "pam-dashboard-dist-"));

async function filesUnder(root, current = root) {
  const output = [];
  for (const entry of await readdir(current, { withFileTypes: true })) {
    const absolute = path.join(current, entry.name);
    const stat = await lstat(absolute);
    if (stat.isSymbolicLink()) {
      throw new Error(`generated output must not contain symlinks: ${absolute}`);
    }
    if (entry.isDirectory()) {
      output.push(...(await filesUnder(root, absolute)));
    } else if (entry.isFile()) {
      output.push(path.relative(root, absolute).split(path.sep).join("/"));
    }
  }
  return output.sort();
}

try {
  const viteCli = path.join(frontendDir, "node_modules", "vite", "bin", "vite.js");
  const result = spawnSync(
    process.execPath,
    [viteCli, "build", "--outDir", temporaryDist, "--emptyOutDir"],
    { cwd: frontendDir, encoding: "utf8" },
  );
  if (result.status !== 0) {
    process.stderr.write(result.stdout ?? "");
    process.stderr.write(result.stderr ?? "");
    throw new Error(`temporary Vite build failed with status ${result.status}`);
  }

  const expectedFiles = await filesUnder(temporaryDist);
  const committedFiles = await filesUnder(committedDist);
  if (JSON.stringify(expectedFiles) !== JSON.stringify(committedFiles)) {
    throw new Error(
      `committed dist file set is stale\nexpected: ${expectedFiles.join(", ")}\nactual: ${committedFiles.join(", ")}`,
    );
  }

  for (const relative of expectedFiles) {
    const expected = await readFile(path.join(temporaryDist, relative));
    const committed = await readFile(path.join(committedDist, relative));
    if (!expected.equals(committed)) {
      throw new Error(`committed dist bytes are stale: ${relative}`);
    }
  }

  console.log(`dist is fresh (${expectedFiles.length} files)`);
} finally {
  await rm(temporaryDist, { recursive: true, force: true });
}
