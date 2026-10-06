#!/usr/bin/env node
/** Offline configuration inspection only; never reads credentials or contacts Kit. */
import {open} from 'node:fs/promises';
import {kitReadiness} from './kit-service.mjs';

const args = process.argv.slice(2);
if (args.length === 1 && args[0] === '--help') {
  console.log('Usage: node scripts/newsletter/kit-readiness.mjs CONFIG.json\nOffline Kit configuration check; no API calls or activation.');
} else if (args.length !== 1 || args[0].startsWith('-')) {
  console.error('One Kit configuration JSON path required (use --help)'); process.exitCode = 2;
} else {
  let handle;
  try {
    handle = await open(args[0], 'r');
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > 65536) throw new Error('Invalid configuration file');
    const buffer = Buffer.alloc(65537);
    const {bytesRead} = await handle.read(buffer, 0, buffer.length, 0);
    if (bytesRead > 65536) throw new Error('Configuration too large');
    const config = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(buffer.subarray(0, bytesRead)));
    const report = kitReadiness(config);
    console.log(JSON.stringify(report, null, 2));
    if (report.errors.length || (report.drafts.enabled && !report.drafts.ready)
        || (report.subscriptions.enabled && !report.subscriptions.ready)) process.exitCode = 1;
  } catch {
    console.error('Unable to validate Kit configuration; file content and paths are not logged'); process.exitCode = 2;
  } finally { await handle?.close(); }
}
