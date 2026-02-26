import olefile

test_file = r"D:\1-Msgs\2008-02-20 160614-R-Corporate Red Alerts - Daily Report.msg"

ole = olefile.OleFileIO(test_file)

print("Properties stream content:")
print("=" * 80)

# Read the properties stream
if ole.exists("__properties_version1.0"):
    stream = ole.openstream("__properties_version1.0")
    data = stream.read()
    print(f"Stream size: {len(data)} bytes")
    print(f"First 200 bytes (hex): {data[:200].hex()}")
    print(f"First 200 bytes (ascii, errors=replace): {data[:200].decode('ascii', errors='replace')}")
    
    # Try to parse as property set
    try:
        props = ole.getproperties("__properties_version1.0")
        print(f"\nParsed properties:")
        for key, value in props.items():
            print(f"  {key}: {value}")
    except Exception as e:
        print(f"\nFailed to parse properties: {e}")

ole.close()
