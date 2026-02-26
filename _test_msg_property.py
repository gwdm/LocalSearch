import sys
sys.path.insert(0, '.')

from localsearch.extractors.msg import MsgExtractor

# Test a file that extract_msg says "does not contain a property stream" but olefile can open
test_file = r"D:\1-Msgs\2008-02-20 160614-R-Corporate Red Alerts - Daily Report.msg"

extractor = MsgExtractor()

print(f"Testing: {test_file}")
print("=" * 80)

# First see what olefile finds
import olefile
ole = olefile.OleFileIO(test_file)
print("Streams found:")
for stream in ole.listdir():
    stream_name = '/'.join(stream)
    print(f"  {stream_name}")
ole.close()

print("\n" + "=" * 80)
print("Attempting extraction...")

try:
    result = extractor.extract(test_file)
    print(f"SUCCESS!")
    print(f"Text length: {len(result.text)}")
    print(f"Metadata: {result.metadata}")
    print(f"\nFirst 500 chars:\n{result.text[:500]}")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
