const fs = require('fs');
const path = require('path');

function assertFileExists(relativePath) {
  const absolutePath = path.resolve(__dirname, '..', relativePath);
  if (!fs.existsSync(absolutePath)) {
    throw new Error(`Missing required desktop asset: ${relativePath}`);
  }
  return absolutePath;
}

const packageJsonPath = path.resolve(__dirname, '..', 'package.json');
const pkg = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));

function assertBuildEntry(entries, entry, label) {
  const exists = entries.some((candidate) => (
    candidate
    && candidate.from === entry.from
    && candidate.to === entry.to
  ));
  if (!exists) {
    throw new Error(
      `${label} is missing required entry: ${entry.from} -> ${entry.to}`,
    );
  }
}

if (pkg.main !== 'main.js') {
  throw new Error(`Unexpected desktop main entry: ${pkg.main}`);
}

['main.js', 'preload.js', 'renderer/loading.html'].forEach(assertFileExists);

const buildFiles = Array.isArray(pkg.build?.files) ? pkg.build.files : [];
['main.js', 'preload.js', 'renderer/**/*'].forEach((entry) => {
  if (!buildFiles.includes(entry)) {
    throw new Error(`Desktop build.files is missing required entry: ${entry}`);
  }
});

const extraResources = Array.isArray(pkg.build?.extraResources) ? pkg.build.extraResources : [];
[
  { from: '../../.env.example', to: '.env.example' },
  { from: '../../dist/backend/stock_analysis', to: 'backend/stock_analysis' },
].forEach((entry) => assertBuildEntry(extraResources, entry, 'Desktop build.extraResources'));

console.log('desktop smoke OK');
