import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {renderEmail} from './email-service.mjs';
const [issueFile, outputDirectory] = process.argv.slice(2);
if (!issueFile || !outputDirectory) throw new Error('Usage: node scripts/newsletter/preview-email.mjs <reviewed-issue.json> <output-directory>');
const issue = JSON.parse(await readFile(issueFile,'utf8'));
const config = JSON.parse(await readFile(new URL('../../daily/config.json',import.meta.url),'utf8'));
const output=resolve(outputDirectory); await mkdir(output,{recursive:true});
for (const locale of ['zh-TW','en']) {
  const email=renderEmail(issue,locale,config.site_url);
  await writeFile(join(output,`${issue.date}-${locale}.html`),email.html,'utf8');
  await writeFile(join(output,`${issue.date}-${locale}.txt`),email.text,'utf8');
}
console.log('Four local email previews created. No provider requests and no email sent.');
