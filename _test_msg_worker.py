"""Test .msg extraction in a ProcessPoolExecutor, just like the real pipeline."""
import os
from concurrent.futures import ProcessPoolExecutor

def init():
    global _ext
    import extract_msg
    _ext = extract_msg

def try_msg(path):
    try:
        msg = _ext.Message(path)
        body = msg.body
        return f"OK: {len(body or '')} chars"
    except Exception as e:
        import traceback
        return f"FAIL: {traceback.format_exc()}"

if __name__ == "__main__":
    folder = r"D:\1-Msgs"
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".msg")][:100]
    print(f"Testing {len(files)} .msg files in ProcessPoolExecutor...")

    ok = fail = 0
    with ProcessPoolExecutor(max_workers=4, initializer=init) as pool:
        for path, result in zip(files, pool.map(try_msg, files)):
            if result.startswith("OK"):
                ok += 1
            else:
                fail += 1
                if fail <= 3:
                    print(f"\n{os.path.basename(path)}")
                    print(result)
    print(f"\nResult: {ok} OK, {fail} FAIL out of {len(files)}")
