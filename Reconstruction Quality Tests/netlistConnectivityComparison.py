import re

#Compare Complete logical netlist to New complete logical netlist tbd


# ============================================================
# Parse the ORIGINAL logical netlist
#
# File format:
#
# Net 1:
#   J501-5
#   <--->  R12-2
#   <--->  SW202-3
#
# ============================================================

def parse_logical_netlist(filename):

    nets = {}

    current_net = None

    with open(filename, "r") as file:

        for line in file:

            line = line.strip()

            # -----------------------------------------------
            # Look for:
            # Net 1:
            # Net 2:
            # -----------------------------------------------
            net_match = re.match(r"Net\s+(\d+):", line)

            if net_match:

                net_number = int(net_match.group(1))

                current_net = f"Net {net_number}"

                nets[current_net] = set()

                continue

            # Ignore lines before the first net
            if current_net is None:
                continue

            # -----------------------------------------------
            # Look for component-pin combinations
            #
            # Examples:
            # J501-5
            # R12-2
            # SW202-3
            # D1-A
            # U1-8
            # -----------------------------------------------
            pin_match = re.search(
                r"\b([A-Za-z]+\d+)-([A-Za-z0-9]+)\b",
                line
            )

            if pin_match:

                reference = pin_match.group(1)
                pin = pin_match.group(2)

                ref_pin = f"{reference}-{pin}"

                nets[current_net].add(ref_pin)

    return nets


# ============================================================
# Parse the RECONSTRUCTED coordinate-based netlist
#
# File format:
#
# Net 1:
#   Pad [Layer 0 @ (1692, 1965)]
#   <--->  Pad [Layer 0 @ (2226, 1573)]
#
# ============================================================

def parse_coordinate_netlist(filename):

    nets = {}

    current_net = None

    with open(filename, "r") as file:

        for line in file:

            line = line.strip()

            # -----------------------------------------------
            # Look for:
            # Net 1:
            # Net 2:
            # -----------------------------------------------
            net_match = re.match(r"Net\s+(\d+):", line)

            if net_match:

                net_number = int(net_match.group(1))

                current_net = f"Net {net_number}"

                nets[current_net] = set()

                continue

            # Ignore lines before the first net
            if current_net is None:
                continue

            # -----------------------------------------------
            # Look for:
            #
            # Pad [Layer 0 @ (1692, 1965)]
            #
            # Capture:
            # Layer = 0
            # X     = 1692
            # Y     = 1965
            # -----------------------------------------------
            pad_match = re.search(
                r"Pad\s+\[Layer\s+(\d+)\s+@\s+\((\d+),\s*(\d+)\)\]",
                line
            )

            if pad_match:

                layer = int(pad_match.group(1))
                x = int(pad_match.group(2))
                y = int(pad_match.group(3))

                pad = (layer, x, y)

                nets[current_net].add(pad)

    return nets


# ============================================================
# Remove the net names.
#
# We don't care whether the original calls something
# "Net 1" and the reconstruction calls it "Net 37".
#
# What matters is what is connected together.
# ============================================================

def normalize_nets(nets):

    normalized = set()

    for pins in nets.values():

        # Ignore nets containing only one item
        if len(pins) > 1:

            normalized.add(frozenset(pins))

    return normalized


# ============================================================
# Print logical netlist
# ============================================================

def print_logical_nets(nets):

    print("\n============================================")
    print("ORIGINAL LOGICAL NETLIST")
    print("============================================")

    for net_name, pins in nets.items():

        print(f"\n{net_name}")

        for pin in sorted(pins):

            print(f"    {pin}")


# ============================================================
# Print coordinate netlist
# ============================================================

def print_coordinate_nets(nets):

    print("\n============================================")
    print("RECONSTRUCTED COORDINATE NETLIST")
    print("============================================")

    for net_name, pads in nets.items():

        print(f"\n{net_name}")

        for layer, x, y in sorted(pads):

            print(f"    Layer {layer}: ({x}, {y})")


# ============================================================
# MAIN PROGRAM
# ============================================================

original_file = "COMPLETE_LOGICAL_NETLIST.txt"

reconstructed_file = "finaltets_netlist.txt"


# ------------------------------------------------------------
# Read both files
# ------------------------------------------------------------

original_nets = parse_logical_netlist(original_file)

reconstructed_nets = parse_coordinate_netlist(reconstructed_file)


# ------------------------------------------------------------
# Convert to connectivity sets
# ------------------------------------------------------------

original_connectivity = normalize_nets(original_nets)

reconstructed_connectivity = normalize_nets(reconstructed_nets)


# ------------------------------------------------------------
# Print results
# ------------------------------------------------------------

print_logical_nets(original_nets)

print_coordinate_nets(reconstructed_nets)


# ============================================================
# SUMMARY
# ============================================================

print("\n============================================")
print("NETLIST SUMMARY")
print("============================================")

print(f"Original nets:       {len(original_nets)}")
print(f"Reconstructed nets:  {len(reconstructed_nets)}")

print(f"Original connectivity groups:      {len(original_connectivity)}")
print(f"Reconstructed connectivity groups: {len(reconstructed_connectivity)}")


# ============================================================
# IMPORTANT:
#
# We CANNOT directly compare the two yet because:
#
# Original:
#     J501-5
#
# Reconstructed:
#     Layer 0: (1692, 1965)
#
# We still need the coordinate -> component/pin mapping.
# ============================================================

print("\n============================================")
print("STATUS")
print("============================================")

print("Original logical netlist successfully parsed.")

print("Reconstructed coordinate netlist successfully parsed.")

print()
print("Next step:")
print("Map reconstructed coordinates to component/pin IDs")
print("using the XMLNetlistMapper.")

print("============================================")