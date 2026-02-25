import inspect, extract_msg

sig = inspect.signature(extract_msg.Message.__init__)
print("Message.__init__ params:")
for name, param in sig.parameters.items():
    default = param.default if param.default is not param.empty else "(required)"
    print(f"  {name}: {default}")

# Check MRO for overrideEncoding
print("\nMRO:")
for cls in extract_msg.Message.__mro__:
    print(f"  {cls.__name__}")

# Check if there's an overrideEncoding param
print("\nSearching for encoding-related params in MSGFile.__init__:")
from extract_msg.msg_classes.msg import MSGFile
sig2 = inspect.signature(MSGFile.__init__)
for name, param in sig2.parameters.items():
    if "encod" in name.lower() or "code" in name.lower() or "override" in name.lower():
        default = param.default if param.default is not param.empty else "(required)"
        print(f"  {name}: {default}")
