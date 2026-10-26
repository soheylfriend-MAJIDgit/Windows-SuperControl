/**
 * Windows-SuperControl - گزینه «ارسال نامه»
 * =====================================================
 * این کد را در Google Apps Script قرار بده و بهصورت «Web app» دیپلوی کن.
 * دستورالعمل کامل و قدمبهقدم توی README.md نوشته شده.
 *
 * کاری که میکند: متنی را که برنامه پایتونی میفرستد میگیرد و در همان
 * پوشه درایو، داخل فایل name.txt بهصورت زنده ذخیره میکند.
 */

const FOLDER_ID   = '1PmMAu537pzN3mjKf_PYctUOlbOIQCUf1'; // همان پوشه Windows-SuperControl
const LETTER_FILE = 'name.txt';                          // فایل زنده نامهها
const SECRET      = '';                                  // اختیاری: یک رمز ساده (هر دو طرف یکسان باشد)
const MAX_CHARS   = 10000;                               // حداکثر طول هر نامه

// هم GET و هم POST را قبول میکنیم، چون وب اپهای گوگل گاهی ریدایرکت میکنند.
function doGet(e)  { return handle(e); }
function doPost(e) { return handle(e); }

function handle(e) {
  let p;
  try {
    p = readParams(e);
  } catch (err) {
    return reply({ ok: false, error: 'bad request: ' + err });
  }

  if (SECRET && String(p.secret || '') !== SECRET) {
    return reply({ ok: false, error: 'wrong secret' });
  }

  const text = String(p.text || '');
  if (text.length > MAX_CHARS) {
    return reply({ ok: false, error: 'text too long (max ' + MAX_CHARS + ')' });
  }

  try {
    const folder = DriveApp.getFolderById(FOLDER_ID);

    // 1) فایل زنده: اگر هست آپدیت شود، اگر نه ساخته شود
    const found = folder.getFilesByName(LETTER_FILE);
    if (found.hasNext()) {
      found.next().setContent(text);
    } else {
      folder.createFile(LETTER_FILE, text, MimeType.PLAIN_TEXT);
    }

    // 2) بایگانی جداگانه فقط وقتی دکمه «ارسال و بایگانی» زده شده
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
      file: LETTER_FILE,
      archive: archiveName,
      chars: text.length,
      time: new Date().toISOString()
    });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
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
