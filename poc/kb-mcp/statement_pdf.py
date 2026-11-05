"""解密國泰對帳單 PDF 並擷取文字（specs/009 research R2、FR-002、FR-012）。

`qpdf --password-file=- --decrypt <in> -`：密碼經 stdin 傳入（不出現在行程參數），
解密結果寫到 stdout，管線接 `pdftotext -layout - -` 擷取保留版面的文字——
解密後的 PDF 不落地。兩個工具以 Homebrew 安裝（`brew install qpdf poppler`）。
launchd 的 PATH 不含 Homebrew（機票排程踩過），所以 `find_tool()` 先找固定路徑。

僅標準庫，Python 3.9 相容。
"""
import os
import shutil
import subprocess
import tempfile

_SEARCH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_TIMEOUT_S = 60


class PdfError(Exception):
    """PDF 處理失敗的共同基底；訊息不含密碼。"""


class PdfToolMissing(PdfError):
    pass


class WrongPassword(PdfError):
    pass


class PdfUnreadable(PdfError):
    pass


def find_tool(name):
    for d in _SEARCH_DIRS:
        path = os.path.join(d, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    found = shutil.which(name)
    if found:
        return found
    raise PdfToolMissing("找不到 %s，請執行 brew install qpdf poppler" % name)


def extract_text(pdf, password):
    """`pdf` 為檔案路徑或 PDF bytes；回傳擷取出的文字（str）。"""
    qpdf = find_tool("qpdf")
    pdftotext = find_tool("pdftotext")
    if isinstance(pdf, (bytes, bytearray)):
        # qpdf 的輸入必須是可 seek 的檔案，且 stdin 已用來傳密碼。
        return _extract_from_bytes(qpdf, pdftotext, bytes(pdf), password)
    if not os.path.isfile(pdf):
        raise PdfUnreadable("找不到 PDF 檔案")
    return _run_pipeline(qpdf, pdftotext, pdf, password)


def _extract_from_bytes(qpdf, pdftotext, data, password):
    """附件 bytes 先寫進只有本人可讀的暫存檔（0600）再交給 qpdf，用完即刪。
    寫進去的是**仍加密的原檔**，解密結果照樣只走管線、不落地（FR-012）。"""
    fd, path = tempfile.mkstemp(prefix="stnd-stmt-", suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return _run_pipeline(qpdf, pdftotext, path, password)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _run_pipeline(qpdf, pdftotext, src, password):
    # 兩個行程的 stderr 都導到暫存檔而非 pipe：沒人讀的 pipe 塞滿（qpdf 對怪 PDF 會大量
    # 警告）會讓 qpdf 卡住、被誤判為逾時。stderr 只有工具訊息，不含解密內容。
    with tempfile.TemporaryFile() as err1_f, tempfile.TemporaryFile() as err2_f:
        p1 = subprocess.Popen(
            [qpdf, "--password-file=-", "--decrypt", src, "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err1_f)
        p2 = subprocess.Popen(
            [pdftotext, "-layout", "-enc", "UTF-8", "-", "-"],
            stdin=p1.stdout, stdout=subprocess.PIPE, stderr=err2_f)
        p1.stdout.close()  # 讓 p2 能在 p1 結束時收到 EOF
        try:
            p1.stdin.write(password.encode("utf-8"))
            p1.stdin.close()
        except BrokenPipeError:
            pass
        try:
            out, _ = p2.communicate(timeout=_TIMEOUT_S)
            p1.wait(timeout=_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p1.kill()
            p2.kill()
            p1.wait()
            p2.wait()
            raise PdfUnreadable("PDF 處理逾時")
        err1_f.seek(0)
        err1 = err1_f.read()
    err1_text = err1.decode("utf-8", "replace")
    if p1.returncode != 0:
        if "invalid password" in err1_text:
            raise WrongPassword("PDF 密碼錯誤（請確認鑰匙圈的 pdf-password，英文字母需大寫）")
        raise PdfUnreadable("PDF 無法開啟（qpdf 結束碼 %d）" % p1.returncode)
    if p2.returncode != 0:
        raise PdfUnreadable("PDF 文字擷取失敗（pdftotext 結束碼 %d）" % p2.returncode)
    return out.decode("utf-8", "replace")
