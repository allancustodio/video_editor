const { spawn, spawnSync } = require('child_process');
const { root, existingVenvPython, systemPython } = require('./python-utils');

let python = existingVenvPython();
let prefix = [];

if (!python) {
  const system = systemPython();
  if (!system) {
    console.error('Python não encontrado. Execute npm run setup depois de instalar o Python 3.11+.');
    process.exit(1);
  }
  python = system.command;
  prefix = system.prefix;
}

const check = spawnSync(python, [...prefix, '-c', "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('streamlit') else 1)"], {
  cwd: root,
  stdio: 'ignore',
  shell: false,
});

if (check.status !== 0) {
  console.error('Dependências Python ainda não instaladas. Execute primeiro: npm run setup');
  process.exit(1);
}

console.log('\nAbrindo Trade Video Cutter em http://localhost:8501\n');
const child = spawn(
  python,
  [...prefix, '-m', 'streamlit', 'run', 'app.py', '--server.headless=true', '--server.address=127.0.0.1', '--server.port=8501'],
  {
    cwd: root,
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
    env: {
      ...process.env,
      STREAMLIT_BROWSER_GATHER_USAGE_STATS: 'false',
      STREAMLIT_SERVER_HEADLESS: 'true',
    },
  }
);

child.stdout.pipe(process.stdout);
child.stderr.pipe(process.stderr);

child.on('error', (error) => {
  console.error(`Não foi possível iniciar a aplicação: ${error.message}`);
  process.exit(1);
});

child.on('exit', (code) => process.exit(code ?? 0));

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}
