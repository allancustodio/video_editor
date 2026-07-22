const path = require('path');
const { root, existingVenvPython, systemPython, run } = require('./python-utils');

console.log('\nConfigurando o ambiente Python local...\n');

let venvPython = existingVenvPython();
if (!venvPython) {
  const python = systemPython();
  if (!python) {
    console.error('Python 3.11+ não foi encontrado. Instale o Python e marque "Add Python to PATH".');
    process.exit(1);
  }

  run(python.command, [...python.prefix, '-m', 'venv', '.venv']);
  venvPython = existingVenvPython();
}

if (!venvPython) {
  console.error('Não foi possível criar o ambiente virtual .venv.');
  process.exit(1);
}

run(venvPython, ['-m', 'pip', 'install', '--upgrade', 'pip']);
run(venvPython, ['-m', 'pip', 'install', '-r', path.join(root, 'requirements.txt')]);

console.log('\nAmbiente pronto. Execute: npm run dev\n');
