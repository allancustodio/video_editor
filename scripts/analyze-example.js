const path = require('path');
const { root, existingVenvPython, systemPython, run } = require('./python-utils');

let python = existingVenvPython();
let prefix = [];
if (!python) {
  const system = systemPython();
  if (!system) {
    console.error('Python não encontrado.');
    process.exit(1);
  }
  python = system.command;
  prefix = system.prefix;
}

run(python, [
  ...prefix,
  'main.py',
  'analyze',
  '--transcript', path.join('examples', 'GMT20260717-114920_Recording.transcript.vtt'),
  '--output', 'output',
  '--speaker', 'RAFAEL FOSSALUSSA',
]);
