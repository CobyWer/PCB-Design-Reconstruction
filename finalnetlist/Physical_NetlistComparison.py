import xml.etree.ElementTree as ET
import re
import math
import matplotlib.pyplot as plt


class NetlistValidator:

    def __init__(
        self,
        board_width_mm,
        board_height_mm,
        img_width_px=2560,
        img_height_px=2550
    ):

        self.board_width = board_width_mm
        self.board_height = board_height_mm

        self.img_width = img_width_px
        self.img_height = img_height_px

        # These MUST match the original mapper
        self.offset_x = 25.4
        self.offset_y = 25.4

        self.scale_x = (
            self.img_width / self.board_width
        )

        self.scale_y = (
            self.img_height / self.board_height
        )


    # ============================================================
    # COORDINATE TRANSFORMATION
    # ============================================================

    def get_rotated_point(
        self,
        local_x,
        local_y,
        global_cx,
        global_cy,
        angle_deg
    ):

        rad = math.radians(angle_deg)

        rot_x = (
            local_x * math.cos(rad)
            - local_y * math.sin(rad)
        )

        rot_y = (
            local_x * math.sin(rad)
            + local_y * math.cos(rad)
        )

        return (
            global_cx + rot_x,
            global_cy + rot_y
        )


    def mm_to_pixel(self, x, y):

        px = int(round(
            (x - self.offset_x)
            * self.scale_x
        ))

        py = int(round(
            (y - self.offset_y)
            * self.scale_y
        ))

        # Same Y flip as original mapper
        py = self.img_height - py

        return px, py


    # ============================================================
    # STEP 1:
    # READ ORIGINAL COORDINATE NETLIST
    # ============================================================

    def read_original_netlist(self, filename):

        print("\nReading original netlist...")

        with open(
            filename,
            'r',
            encoding='utf-8'
        ) as f:

            data = f.read()


        # Same format as your original mapper
        raw_nets = data.split("Net ")

        nets = []


        # Matches:
        # Pad [Layer 1 @ (1234, 567)]
        pad_pattern = re.compile(
            r'Pad \[Layer \d+ @ \(\s*(\d+)\s*,\s*(\d+)\s*\)\]'
        )


        for raw_net in raw_nets[1:]:

            lines = raw_net.strip().split('\n')

            if not lines:
                continue


            # Net name
            net_name = (
                lines[0]
                .replace(':', '')
                .strip()
            )


            # Find all coordinates
            coordinates = pad_pattern.findall(
                raw_net
            )


            points = []

            for x, y in coordinates:

                points.append({
                    'x': int(x),
                    'y': int(y)
                })


            if points:

                nets.append({
                    'name': net_name,
                    'points': points
                })


        total_points = sum(
            len(net['points'])
            for net in nets
        )


        print(
            f"Found {len(nets)} nets "
            f"and {total_points} coordinates."
        )


        return nets


    # ============================================================
    # STEP 2:
    # READ IPC-2581 AND FIND COMPONENT PIN LOCATIONS
    # ============================================================

    def parse_vcu_xml(self, filename):

        print("\nParsing IPC-2581 file...")

        namespace = {
            'ipc': 'http://webstds.ipc.org/2581'
        }


        pin_locations = {}


        tree = ET.parse(filename)

        root = tree.getroot()


        # --------------------------------------------------------
        # Extract package pin positions
        # --------------------------------------------------------

        packages = {}


        for pkg in root.findall(
            './/ipc:Package',
            namespace
        ):

            pkg_name = pkg.attrib.get(
                'name'
            )

            pins = {}


            for pin in pkg.findall(
                './/ipc:Pin',
                namespace
            ):

                pin_num = pin.attrib.get(
                    'number'
                )

                loc = pin.find(
                    'ipc:Location',
                    namespace
                )


                if (
                    loc is not None
                    and pin_num is not None
                ):

                    x = float(
                        loc.attrib.get(
                            'x',
                            0
                        )
                    )

                    y = float(
                        loc.attrib.get(
                            'y',
                            0
                        )
                    )

                    pins[pin_num] = (
                        x,
                        y
                    )


            packages[pkg_name] = pins


        # --------------------------------------------------------
        # Extract component locations
        # --------------------------------------------------------

        component_count = 0


        for comp in root.findall(
            './/ipc:Component',
            namespace
        ):

            ref_des = comp.attrib.get(
                'refDes'
            )

            pkg_name = comp.attrib.get(
                'packageRef'
            )


            if (
                not ref_des
                or pkg_name not in packages
            ):
                continue


            comp_loc = comp.find(
                'ipc:Location',
                namespace
            )


            if comp_loc is None:
                continue


            cx = float(
                comp_loc.attrib.get(
                    'x',
                    0
                )
            )

            cy = float(
                comp_loc.attrib.get(
                    'y',
                    0
                )
            )


            # Component rotation
            xform = comp.find(
                'ipc:Xform',
                namespace
            )


            if xform is not None:

                rotation = float(
                    xform.attrib.get(
                        'rotation',
                        0
                    )
                )

            else:

                rotation = 0


            # ----------------------------------------------------
            # Calculate every pin's global pixel position
            # ----------------------------------------------------

            for pin_num, (
                local_x,
                local_y
            ) in packages[pkg_name].items():

                global_x, global_y = (
                    self.get_rotated_point(
                        local_x,
                        local_y,
                        cx,
                        cy,
                        rotation
                    )
                )


                px, py = self.mm_to_pixel(
                    global_x,
                    global_y
                )


                pin_name = (
                    f"{ref_des}-{pin_num}"
                )


                pin_locations[pin_name] = (
                    px,
                    py
                )


            component_count += 1


        print(
            f"Found {len(pin_locations)} pins "
            f"from {component_count} components."
        )


        return pin_locations


    # ============================================================
    # READ CLEANED LOGICAL NETLIST
    # ============================================================

    def read_logical_netlist(
        self,
        filename
    ):

        print("\nReading mapped logical netlist...")

        with open(
            filename,
            'r',
            encoding='utf-8'
        ) as f:

            data = f.read()


        raw_nets = data.split("Net ")

        nets = []


        for raw_net in raw_nets[1:]:

            lines = raw_net.strip().split('\n')


            if not lines:
                continue


            net_name = (
                lines[0]
                .replace(':', '')
                .strip()
            )


            pins = []


            for line in lines[1:]:

                line = line.strip()


                if not line:
                    continue


                # Remove <---> arrows
                line = line.replace(
                    '<--->',
                    ''
                ).strip()


                if line:
                    pins.append(line)


            if len(pins) >= 2:

                nets.append({
                    'name': net_name,
                    'pins': pins
                })


        print(
            f"Found {len(nets)} mapped nets."
        )


        return nets


    # ============================================================
    # STEP 2 FIGURE:
    # PLOT RECONSTRUCTED NETLIST
    # ============================================================

    def plot_reconstructed(
        self,
        logical_nets,
        pin_locations
    ):

        plt.figure(
            figsize=(12, 10)
        )


        for net in logical_nets:

            net_name = net['name']

            pins = net['pins']


            x_values = []

            y_values = []


            for pin in pins:

                if pin not in pin_locations:

                    continue


                x, y = pin_locations[pin]

                x_values.append(x)

                y_values.append(y)


            if not x_values:
                continue


            # Plot pins
            plt.scatter(
                x_values,
                y_values,
                s=25,
                label=net_name
            )


            # Connect pins belonging to this net
            if len(x_values) >= 2:

                plt.plot(
                    x_values,
                    y_values,
                    linewidth=1,
                    alpha=0.5
                )


        plt.gca().invert_yaxis()

        plt.xlabel("X (pixels)")

        plt.ylabel("Y (pixels)")

        plt.title(
            "Reconstructed Logical Netlist"
        )

        plt.grid(
            True,
            alpha=0.3
        )

        plt.axis('equal')

        plt.tight_layout()


    # ============================================================
    # STEP 1 FIGURE:
    # PLOT ORIGINAL INPUT
    # ============================================================

    def plot_original(
        self,
        original_nets
    ):

        plt.figure(
            figsize=(12, 10)
        )


        for net in original_nets:

            net_name = net['name']

            points = net['points']


            x_values = [
                point['x']
                for point in points
            ]

            y_values = [
                point['y']
                for point in points
            ]


            plt.scatter(
                x_values,
                y_values,
                s=15,
                label=net_name
            )


        plt.gca().invert_yaxis()

        plt.xlabel("X (pixels)")

        plt.ylabel("Y (pixels)")

        plt.title(
            "Original PCB Netlist Coordinates"
        )

        plt.grid(
            True,
            alpha=0.3
        )

        plt.axis('equal')

        plt.tight_layout()


    # ============================================================
    # STEP 3:
    # OVERLAY ORIGINAL + RECONSTRUCTED
    # ============================================================

    def plot_overlay(
        self,
        original_nets,
        logical_nets,
        pin_locations
    ):

        plt.figure(
            figsize=(12, 10)
        )


        # --------------------------------------------------------
        # Build a lookup table for logical nets
        # --------------------------------------------------------

        logical_net_lookup = {}

        for net in logical_nets:

            logical_net_lookup[
                net['name']
            ] = net['pins']


        # --------------------------------------------------------
        # Plot each original coordinate
        # and its corresponding mapped pin
        # --------------------------------------------------------

        total_mappings = 0

        distances = []


        for original_net in original_nets:

            net_name = original_net['name']

            points = original_net['points']


            # Get corresponding mapped pins
            mapped_pins = logical_net_lookup.get(
                net_name,
                []
            )


            # ----------------------------------------------------
            # Plot original coordinates
            # ----------------------------------------------------

            original_x = [
                point['x']
                for point in points
            ]

            original_y = [
                point['y']
                for point in points
            ]


            plt.scatter(
                original_x,
                original_y,
                s=20,
                alpha=0.5
            )


            # ----------------------------------------------------
            # Match each original coordinate to its mapped pin
            #
            # IMPORTANT:
            #
            # The original mapper performs the same nearest-pin
            # search. We reproduce that here.
            # ----------------------------------------------------

            for point in points:

                original_x = point['x']

                original_y = point['y']


                closest_pin = None

                min_distance = float('inf')


                for pin in mapped_pins:

                    if pin not in pin_locations:
                        continue


                    px, py = pin_locations[pin]


                    distance = math.hypot(
                        original_x - px,
                        original_y - py
                    )


                    if distance < min_distance:

                        min_distance = distance

                        closest_pin = pin


                # ------------------------------------------------
                # Draw mapping line
                # ------------------------------------------------

                if closest_pin is not None:

                    px, py = pin_locations[
                        closest_pin
                    ]


                    plt.plot(
                        [original_x, px],
                        [original_y, py],
                        linewidth=0.5,
                        alpha=0.4
                    )


                    plt.scatter(
                        px,
                        py,
                        s=25,
                        marker='x'
                    )


                    distances.append(
                        min_distance
                    )

                    total_mappings += 1


        # --------------------------------------------------------
        # Statistics
        # --------------------------------------------------------

        if distances:

            average_error = (
                sum(distances)
                / len(distances)
            )

            maximum_error = max(
                distances
            )

            median_error = sorted(
                distances
            )[len(distances) // 2]


            print("\nMapping Validation")
            print(
                "----------------------------"
            )

            print(
                f"Mappings checked: {total_mappings}"
            )

            print(
                f"Average error:    "
                f"{average_error:.2f} pixels"
            )

            print(
                f"Median error:     "
                f"{median_error:.2f} pixels"
            )

            print(
                f"Maximum error:    "
                f"{maximum_error:.2f} pixels"
            )


        plt.gca().invert_yaxis()

        plt.xlabel("X (pixels)")

        plt.ylabel("Y (pixels)")

        plt.title(
            "Original vs. Reconstructed Netlist"
        )

        plt.grid(
            True,
            alpha=0.3
        )

        plt.axis('equal')

        plt.tight_layout()


    # ============================================================
    # RUN EVERYTHING
    # ============================================================

    def run_validation(self):

        # --------------------------------------------------------
        # Read original coordinate netlist
        # --------------------------------------------------------

        original_nets = self.read_original_netlist(
            "finaltets_netlist.txt"
        )


        # --------------------------------------------------------
        # Read IPC-2581 component/pin locations
        # --------------------------------------------------------

        pin_locations = self.parse_vcu_xml(
            "IPC_2581_VCU.txt"
        )


        # --------------------------------------------------------
        # Read mapped logical netlist
        # --------------------------------------------------------

        logical_nets = self.read_logical_netlist(
            "COMPLETE_LOGICAL_NETLIST.txt"
        )


        # --------------------------------------------------------
        # Figure 1
        # --------------------------------------------------------

        self.plot_original(
            original_nets
        )


        # --------------------------------------------------------
        # Figure 2
        # --------------------------------------------------------

        self.plot_reconstructed(
            logical_nets,
            pin_locations
        )


        # --------------------------------------------------------
        # Figure 3
        # --------------------------------------------------------

        self.plot_overlay(
            original_nets,
            logical_nets,
            pin_locations
        )


        # Display all three
        plt.show()


# ================================================================
# MAIN
# ================================================================

if __name__ == "__main__":

    print(
        "--- PCB Netlist Validation ---"
    )


    width = float(
        input(
            "Enter board width in mm: "
        )
    )


    height = float(
        input(
            "Enter board height in mm: "
        )
    )


    validator = NetlistValidator(
        board_width_mm=width,
        board_height_mm=height
    )


    validator.run_validation()