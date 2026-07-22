const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.resolve(__dirname, '..');

function existingVenvPython() {
  const candidates = process.platform === 'win32'
    ? [path.join(root, '.venv', 'Scripts', 'python.exe')]
    : [path.join(root, '.venv', 'bin', 'python')];

  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function systemPython() {
  const candidates = process.platform === 'win32'
    ? [
        { command: 'py', prefix: ['-3'] },
        { command: 'python', prefix: [] },
      ]
    : [
        { command: 'python3', prefix: [] },
        { command: 'python', prefix: [] },
      ];

  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, [...candidate.prefix, '--version'], {
      cwd: root,
      encoding: 'utf8',
      shell: false,
    });
    if (result.status === 0) return candidate;
  }
  return null;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: 'inherit',
    shell: false,
    ...options,
  });

  if (result.error) {
    console.error(`Falha ao executar ${command}: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status || 1);
  return result;
}

module.exports = { root, existingVenvPython, systemPython, run };
