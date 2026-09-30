import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

/**
 * Generates dist/sw.js from src/sw.template.js after the build:
 * every emitted file goes into the precache list, and the cache version
 * is a hash of their contents, so each deploy gets a fresh cache.
 */
function serviceWorker(): Plugin {
  let outDir = 'dist';
  let root = '.';
  return {
    name: 'svyaz-service-worker',
    apply: 'build',
    configResolved(config) {
      root = config.root;
      outDir = resolve(root, config.build.outDir);
    },
    closeBundle() {
      const files: string[] = [];
      const walk = (dir: string) => {
        for (const name of readdirSync(dir)) {
          const full = join(dir, name);
          if (statSync(full).isDirectory()) walk(full);
          else if (name !== 'sw.js') files.push(full);
        }
      };
      walk(outDir);
      const hash = createHash('sha256');
      for (const f of files.sort()) hash.update(relative(outDir, f)).update(readFileSync(f));
      const precache = ['./', ...files.map((f) => './' + relative(outDir, f).split('\\').join('/'))];
      const template = readFileSync(resolve(root, 'src/sw.template.js'), 'utf8');
      const sw = template
        .replace("'__VERSION__'", JSON.stringify(hash.digest('hex').slice(0, 12)))
        .replace('__PRECACHE__', JSON.stringify(precache, null, 2));
      writeFileSync(join(outDir, 'sw.js'), sw);
    },
  };
}

export default defineConfig({
  base: './',
  plugins: [react(), serviceWorker()],
});
