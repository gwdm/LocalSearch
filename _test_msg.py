import sys
sys.path.insert(0, '.')

from localsearch.extractors.msg import MsgExtractor

# Test one of the failing files
test_file = r"D:\1-Msgs\2007-10-16 180426-R-RE Programme Team Meeting - 1810.msg"

extractor = MsgExtractor()

print(f"Testing: {test_file}")
print("=" * 80)

try:
    result = extractor.extract(test_file)
    print(f"SUCCESS!")
    print(f"Text length: {len(result.text)}")
    print(f"Metadata: {result.metadata}")
    print(f"\nFirst 500 chars:\n{result.text[:500]}")
except Exception as e:
    print(f"FAILED: {e}")
    print(f"\nException type: {type(e).__name__}")
    
    # Try to debug further
    print("\n" + "=" * 80)
    print("DEBUG: Testing extract_msg directly...")
    try:
        import extract_msg
        msg = extract_msg.Message(test_file)
        print(f"Message opened successfully")
        print(f"Subject: {msg.subject}")
        print(f"Sender: {msg.sender}")
        print(f"Body length: {len(msg.body) if msg.body else 0}")
        print(f"Body: {msg.body[:200] if msg.body else '(none)'}")
        msg.close()
    except Exception as e2:
        print(f"extract_msg also failed: {e2}")
        
    print("\n" + "=" * 80)
    print("DEBUG: Testing olefile...")
    try:
        import olefile
        ole = olefile.OleFileIO(test_file)
        print(f"OleFile opened successfully")
        print(f"Streams available:")
        for stream in ole.listdir():
            print(f"  {'/'.join(stream)}")
        ole.close()
    except Exception as e3:
        print(f"olefile also failed: {e3}")
