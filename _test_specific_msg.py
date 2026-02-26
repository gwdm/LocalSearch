import sys
import os
sys.path.insert(0, '.')

test_file = r"D:\1-Msgs\2021-10-24 093145-R-.msg"

print(f"Testing: {test_file}")
print(f"File exists: {os.path.exists(test_file)}")
print(f"File size: {os.path.getsize(test_file):,} bytes" if os.path.exists(test_file) else "N/A")
print("=" * 80)

# Try extract_msg
try:
    import extract_msg
    msg = extract_msg.Message(test_file)
    print(f"extract_msg: SUCCESS")
    print(f"  Subject: {msg.subject}")
    print(f"  Sender: {msg.sender}")
    print(f"  Body: {msg.body[:200] if msg.body else '(none)'}")
    msg.close()
except Exception as e:
    print(f"extract_msg: FAILED - {e}")

# Try olefile
print("\n" + "=" * 80)
try:
    import olefile
    ole = olefile.OleFileIO(test_file)
    streams = list(ole.listdir())
    print(f"olefile: SUCCESS - {len(streams)} streams found")
    for stream in streams[:10]:  # Show first 10
        print(f"  {'/'.join(stream)}")
    ole.close()
except Exception as e:
    print(f"olefile: FAILED - {e}")

# Now try the extractor
print("\n" + "=" * 80)
from localsearch.extractors.msg import MsgExtractor
extractor = MsgExtractor()

try:
    result = extractor.extract(test_file)
    print(f"MsgExtractor: SUCCESS")
    print(f"Text length: {len(result.text)}")
    print(f"Metadata: {result.metadata}")
except Exception as e:
    print(f"MsgExtractor: FAILED - {e}")
    
    import traceback
    print("\nFull traceback:")
    traceback.print_exc()
