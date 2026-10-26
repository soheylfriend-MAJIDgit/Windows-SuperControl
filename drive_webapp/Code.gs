/**
 * Windows-SuperControl - گزینه «ارسال نامه» + استعلام
 * =====================================================
 * این کد را در Google Apps Script قرار بده و بهصورت «Web app» دیپلوی کن.
 * (اگر قبلاً دیپلوی کردهای: Deploy -> Manage deployments -> New version -> Deploy)
 *
 * تغییرات این نسخه:
 *   - بعد از نوشتن، همان فایل را دوباره از درایو میخواند (read-back) و نتیجه را
 *     همراه زمانبندی سرور برمیگرداند: verified / echo / server_write_ms / server_read_ms
 *   - حالت action=check فقط میخواند و هیچ چیزی نمینویسد (استعلام خالص)
 */

const FOLDER_ID       = '1PmMAu537pzN3mjKf_PYctUOlbOIQCUf1'; // پوشه Windows-SuperControl
const LETTER_FILE_ID  = '1fzI9jceihjTmeJ4wYguWYA0EGMV3EcMP'; // فایل name.txt
const LETTER_FILE     = 'name.txt';
const SECRET          = '';                                  // اختیاری؛ هردو طرف یکسان باشد
const MAX_CHARS       = 10000;

function doGet(e)  { return handle(e); }
function doPost(e) { return handle(e); }

function handle(e) {
  const started = Date.now();
  let p;
  try {
    p = readParams(e);
  } catch (err) {
    return reply({ ok: false, error: 'bad request: ' + err });
  }

  if (SECRET && String(p.secret || '') !== SECRET) {
    return reply({ ok: false, error: 'wrong secret' });
  }

  // ---------- حالت استعلام خالص: فقط خواندن، بدون نوشتن ----------
  if (String(p.action || '') === 'check') {
    try {
      const file = getLetterFile();
      const content = file.getBlob().getDataAsString('UTF-8');
      return reply({
        ok: true, action: 'check', file: LETTER_FILE,
        text: content, chars: content.length,
        server_ms: Date.now() - started,
        time: new Date().toISOString()
      });
    } catch (err) {
      return reply({ ok: false, action: 'check', error: String(err) });
    }
  }

  // ---------- حالت نوشتن ----------
  const text = String(p.text || '');
  if (text.length > MAX_CHARS) {
    return reply({ ok: false, error: 'text too long (max ' + MAX_CHARS + ')' });
  }

  try {
    const folder = DriveApp.getFolderById(FOLDER_ID);
    const file = getLetterFile();

    const w0 = Date.now();
    file.setContent(text);
    const writeMs = Date.now() - w0;

    // *** استعلام: دوباره همان فایل را از درایو میخوانیم ***
    const r0 = Date.now();
    const echo = getLetterFile().getBlob().getDataAsString('UTF-8');
    const readMs = Date.now() - r0;
    const verified = (echo === text);

    let archiveName = '';
    if (String(p.archive || '') === '1' && text.trim()) {
      const stamp = Utilities.formatDate(
        new Date(), Session.getScriptTimeZone(), 'yyyyMMdd-HHmmss'
      );
      archiveName = 'name-' + stamp + '.txt';
      folder.createFile(archiveName, text, MimeType.PLAIN_TEXT);
    }

    return reply({
      ok: true,
      verified: verified,
      echo: echo,
      file: LETTER_FILE,
      archive: archiveName,
      chars: text.length,
      server_write_ms: writeMs,
      server_read_ms: readMs,
      server_total_ms: Date.now() - started,
      time: new Date().toISOString()
    });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

/** فایل نامه را با آیدی ثابت پیدا میکند؛ اگر پاک شده باشد دوباره میسازد. */
function getLetterFile() {
  try {
    return DriveApp.getFileById(LETTER_FILE_ID);
  } catch (err) {
    const folder = DriveApp.getFolderById(FOLDER_ID);
    const found = folder.getFilesByName(LETTER_FILE);
    if (found.hasNext()) return found.next();
    return folder.createFile(LETTER_FILE, '', MimeType.PLAIN_TEXT);
  }
}

/** پارامترها را از query string، فرم POST یا بدنه JSON میگیرد. */
function readParams(e) {
  const p = {};
  if (e && e.parameter) {
    Object.keys(e.parameter).forEach(function (k) { p[k] = e.parameter[k]; });
  }
  if (e && e.postData && e.postData.contents) {
    const raw = e.postData.contents;
    try {
      const j = JSON.parse(raw);
      Object.keys(j).forEach(function (k) { p[k] = j[k]; });
      return p;
    } catch (_) { /* فرم urlencoded است */ }
    raw.split('&').forEach(function (pair) {
      const i = pair.indexOf('=');
      if (i < 0) return;
      const key = decodeURIComponent(pair.slice(0, i).replace(/\+/g, ' '));
      p[key] = decodeURIComponent(pair.slice(i + 1).replace(/\+/g, ' '));
    });
  }
  return p;
}

function reply(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
