import re

input_file  = "constant/polyMesh/boundary"
output_file = "constant/polyMesh/boundary"

def classify(name: str) -> tuple[str, str]:
    """
    return (type, physicalType)
    """
    # cyclic pair
    if name in ("front", "back"):
        return ("wedge", "wedge")

    # walls
    if name.startswith("wall"):
        return ("wall", "wall")

    # inlets/outlets (keep as patch)
    if name.startswith("inlet") or name.startswith("outlet"):
        return ("patch", "patch")

    # default: leave unchanged
    return ("", "")

def update_block(block: str) -> str:
    # block begins with boundary name line like: "front { ... }"
    m = re.match(r"\s*([A-Za-z0-9_]+)\s*\{", block)
    if not m:
        return block
    name = m.group(1)

    new_type, new_phys = classify(name)
    if not new_type:
        return block

    # replace type
    if re.search(r"\btype\s+\w+\s*;", block):
        block = re.sub(r"(\btype\s+)\w+(\s*;)", rf"\1{new_type}\2", block)
    else:
        block = block.replace("{", "{\n        type            " + new_type + ";", 1)

    # replace physicalType
    if re.search(r"\bphysicalType\s+\w+\s*;", block):
        block = re.sub(r"(\bphysicalType\s+)\w+(\s*;)", rf"\1{new_phys}\2", block)
    else:
        block = block.replace("{", "{\n        physicalType    " + new_phys + ";", 1)

    return block

# --- read whole file
with open(input_file, "r") as f:
    text = f.read()

# --- safer block matcher: patchName { ... } (non-greedy)
# This assumes no nested braces inside each patch block (true for boundary file).
pattern = re.compile(r"(^\s*[A-Za-z0-9_]+\s*\{.*?^\s*\})", re.MULTILINE | re.DOTALL)

text2 = pattern.sub(lambda m: update_block(m.group(1)), text)

with open(output_file, "w") as f:
    f.write(text2)

print("Updated:", output_file)