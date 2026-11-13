import fs from 'node:fs';
import path from 'node:path';

export const contribModules = ['calendar', 'ledger', 'eggs', 'bee', 'fungi', 'crop_plan', 'grazing_plan'];

export function selectedModules() {
  const selected = process.env.CONTRIB_MODULES ? process.env.CONTRIB_MODULES.split(',') : contribModules;
  if (!selected.length || selected.some(module => !contribModules.includes(module))) {
    throw new Error(`CONTRIB_MODULES must select from ${contribModules.join(',')}`);
  }
  return selected;
}

export function rememberRecord(module, record) {
  if (!contribModules.includes(module)) throw new Error(`Unknown module: ${module}`);
  const directory = path.join(process.env.TEST_ARTIFACTS || './artifacts', 'contrib-records');
  fs.mkdirSync(directory, { recursive: true });
  const file = path.join(directory, `${module}.json`);
  const records = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : [];
  records.push(record);
  fs.writeFileSync(file, JSON.stringify(records, null, 2));
}
