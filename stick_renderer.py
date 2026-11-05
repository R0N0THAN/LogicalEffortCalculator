import tkinter as tk
from tkinter import ttk

# =====================================================================
# EULER PATH & STICK DIAGRAM NODE MAPPING (Separated Inverter Model)
# =====================================================================
def get_gate_stick_layout(node):
    gtype = node['type']
    nin = node['inputs']

    if gtype == 'INV':
        inputs = ['A']
        p_contacts = [{'idx': 0, 'type': 'VDD'}, {'idx': 1, 'type': 'Y'}]
        n_contacts = [{'idx': 0, 'type': 'GND'}, {'idx': 1, 'type': 'Y'}]
        p_sd = ['S', 'D']
        n_sd = ['S', 'D']

    elif gtype == 'NAND':
        inputs = [chr(65 + i) for i in range(nin)]
        p_contacts = [{'idx': i, 'type': 'VDD' if i % 2 == 0 else 'Y'} for i in range(nin + 1)]
        p_sd = ['S' if i % 2 == 0 else 'D' for i in range(nin + 1)]

        n_contacts = [{'idx': 0, 'type': 'GND'}, {'idx': nin, 'type': 'Y'}]
        n_sd = ['S'] + ['D/S' for _ in range(nin - 1)] + ['D']

    elif gtype == 'NOR':
        inputs = [chr(65 + i) for i in range(nin)]
        p_contacts = [{'idx': 0, 'type': 'VDD'}, {'idx': nin, 'type': 'Y'}]
        p_sd = ['S'] + ['D/S' for _ in range(nin - 1)] + ['D']

        n_contacts = [{'idx': i, 'type': 'GND' if i % 2 == 0 else 'Y'} for i in range(nin + 1)]
        n_sd = ['S' if i % 2 == 0 else 'D' for i in range(nin + 1)]

    elif gtype in ('XOR', 'XNOR'):
        inputs = ['A', "A'", "B'", 'B']
        if gtype == 'XNOR':
            inputs[2], inputs[3] = inputs[3], inputs[2]
        p_contacts = [
            {'idx': 0, 'type': 'VDD'},
            {'idx': 1, 'type': 'XOR_BRANCH'},
            {'idx': 2, 'type': 'Y'},
            {'idx': 3, 'type': 'XOR_BRANCH'},
            {'idx': 4, 'type': 'VDD'}
        ]
        n_contacts = [
            {'idx': 0, 'type': 'GND_M2'},
            {'idx': 1, 'type': 'Y'},
            {'idx': 3, 'type': 'GND'},
            {'idx': 4, 'type': 'GND_M2'}
        ]
        p_sd = ['S', 'D/S', 'D', 'D/S', 'S']
        n_sd = ['S', 'D/S', 'D', 'D/S', 'S']

    else:
        inputs = ['A']
        p_contacts = [{'idx': 0, 'type': 'VDD'}, {'idx': 1, 'type': 'Y'}]
        n_contacts = [{'idx': 0, 'type': 'GND'}, {'idx': 1, 'type': 'Y'}]
        p_sd = ['S', 'D']
        n_sd = ['S', 'D']

    return {
        'node_id': node['id'],
        'name': node.get('name', f"{gtype}{node['id']}"),
        'gtype': gtype,
        'nin': len(inputs),
        'inputs': inputs,
        'p_contacts': p_contacts,
        'n_contacts': n_contacts,
        'p_sd': p_sd,
        'n_sd': n_sd,
        'size': node.get('size', 1.0)
    }


# =====================================================================
# STICK DIAGRAM WINDOW RENDERER
# =====================================================================
class StickDiagramWindow(tk.Toplevel):
    def __init__(self, parent, graph_data):
        super().__init__(parent)
        self.graph_data = graph_data
        self.title("CMOS Stick Diagram Renderer")
        self.geometry("1120x700")
        self.configure(bg="#11111b")

        # Top Control Bar & Color Legend
        top_bar = ttk.Frame(self, padding=8)
        top_bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top_bar, text="Select Logic Gate:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        
        self.logic_nodes = [n for n in self.graph_data['nodes'] if n['type'] not in ('INPUT', 'OUTPUT')]
        self.gate_options = ["All Schematic Gates (Side-by-Side)"] + [
            f"Gate #{n['id']}: {n.get('name', n['type'])} ({n['inputs']}-input {n['type']})" for n in self.logic_nodes
        ]

        self.gate_combo = ttk.Combobox(top_bar, values=self.gate_options, state="readonly", width=42)
        self.gate_combo.current(0)
        self.gate_combo.pack(side=tk.LEFT, padx=5)
        self.gate_combo.bind("<<ComboboxSelected>>", lambda e: self.render_stick_diagram())

        leg_frame = ttk.Frame(top_bar)
        leg_frame.pack(side=tk.RIGHT, padx=5)
        
        self.create_legend_badge(leg_frame, "Metal-1", "#42a5f5")
        self.create_legend_badge(leg_frame, "Metal-2", "#ab47bc")
        self.create_legend_badge(leg_frame, "Poly", "#ef5350")
        self.create_legend_badge(leg_frame, "pDIFF", "#ffca28")
        self.create_legend_badge(leg_frame, "nDIFF", "#66bb6a")
        self.create_legend_badge(leg_frame, "Contact (●)", "#ffffff")
        self.create_legend_badge(leg_frame, "Source / Drain", "#ff7043")

        self.canvas = tk.Canvas(self, bg="#1e1e2e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Pan & Zoom State
        self.zoom = 1.0
        self.pan_x = 50.0
        self.pan_y = 30.0
        self.pan_start = None

        self.canvas.bind("<ButtonPress-2>", self.start_pan)
        self.canvas.bind("<B2-Motion>", self.do_pan)
        self.canvas.bind("<ButtonPress-3>", self.start_pan)
        self.canvas.bind("<B3-Motion>", self.do_pan)
        self.canvas.bind("<MouseWheel>", self.on_zoom_wheel)

        self.render_stick_diagram()

    def create_legend_badge(self, parent, text, color):
        lbl = tk.Label(parent, text=text, bg=color, fg="#11111b", font=("Arial", 8, "bold"), padx=5, pady=2)
        lbl.pack(side=tk.LEFT, padx=3)

    def start_pan(self, event):
        self.pan_start = (event.x, event.y)

    def do_pan(self, event):
        if self.pan_start:
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            self.pan_x += dx
            self.pan_y += dy
            self.pan_start = (event.x, event.y)
            self.render_stick_diagram()

    def on_zoom_wheel(self, event):
        factor = 1.1 if event.delta > 0 else 0.9
        self.zoom = max(0.4, min(2.5, self.zoom * factor))
        self.render_stick_diagram()

    def to_screen(self, x, y):
        return (x * self.zoom + self.pan_x, y * self.zoom + self.pan_y)

    def draw_contact_cut(self, x, y):
        sx, sy = self.to_screen(x, y)
        r = max(5, int(7 * self.zoom))
        self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, fill="#ffffff", outline="#11111b", width=2)
        self.canvas.create_oval(sx - r + 3, sy - r + 3, sx + r - 3, sy + r - 3, fill="#11111b", outline="#11111b")

    def render_stick_diagram(self):
        c = self.canvas
        c.delete("all")

        if not self.logic_nodes:
            c.create_text(400, 250, text="No logic gates found in schematic.", fill="#ffffff", font=("Arial", 12))
            return

        sel_idx = self.gate_combo.current()
        if sel_idx == 0:
            target_gates = [get_gate_stick_layout(n) for n in self.logic_nodes]
        else:
            target_gates = [get_gate_stick_layout(self.logic_nodes[sel_idx - 1])]

        c_metal = "#42a5f5"  # Metal-1 Blue
        c_metal2 = "#ab47bc"  # Metal-2 Purple
        c_poly = "#ef5350"   # Polysilicon Red
        c_pdiff = "#ffca28"  # P-Diff Yellow
        c_ndiff = "#66bb6a"  # N-Diff Green
        c_sd = "#ff7043"     # Source/Drain Orange

        start_x = 80
        gate_widths = [(len(gate['inputs']) + 1) * 90 + 60 for gate in target_gates]
        rail_end_x = start_x + sum(gate_widths) + 80 * (len(target_gates) - 1)

        # All gates in the schematic share continuous power rails.
        vx1, vy1 = self.to_screen(start_x, 60)
        vx2, _ = self.to_screen(rail_end_x, 60)
        c.create_line(vx1, vy1, vx2, vy1, fill=c_metal, width=max(4, int(6 * self.zoom)))
        c.create_text(vx2 + 25, vy1, text="VDD", fill="#ffffff", font=("Arial", max(9, int(12 * self.zoom)), "bold"))

        gx1, gy1 = self.to_screen(start_x, 400)
        gx2, _ = self.to_screen(rail_end_x, 400)
        c.create_line(gx1, gy1, gx2, gy1, fill=c_metal, width=max(4, int(6 * self.zoom)))
        c.create_text(gx2 + 25, gy1, text="GND", fill="#ffffff", font=("Arial", max(9, int(12 * self.zoom)), "bold"))

        shared_terminal_indices = set()
        for gate_index, (left_gate, right_gate) in enumerate(zip(target_gates, target_gates[1:]), start=1):
            left_last_idx = len(left_gate['inputs'])
            left_p_terminal = next(
                (contact['type'] for contact in left_gate['p_contacts'] if contact['idx'] == left_last_idx),
                None
            )
            right_p_terminal = next(
                (contact['type'] for contact in right_gate['p_contacts'] if contact['idx'] == 0),
                None
            )
            if left_p_terminal == right_p_terminal == 'VDD':
                shared_terminal_indices.add((gate_index, 'p', 0))

        gate_geometry = []
        for gate_index, gate in enumerate(target_gates):
            inputs = gate['inputs']
            p_contacts = gate['p_contacts']
            n_contacts = gate['n_contacts']
            p_sd = gate['p_sd']
            n_sd = gate['n_sd']
            num_inputs = len(inputs)
            num_nodes = num_inputs + 1
            gate_title = f"{gate['name']} ({gate['gtype']})"

            col_w = 90
            gate_width = num_nodes * col_w + 60

            # Vertical Layout Y Coordinates
            y_vdd = 60
            y_pdiff = 150
            y_well = 230    # Demarcation Line level
            y_ndiff = 310
            y_gnd = 400

            node_x_coords = [start_x + i * col_w + 40 for i in range(num_nodes)]
            poly_x_coords = [(node_x_coords[i] + node_x_coords[i+1]) / 2 for i in range(num_inputs)]
            gate_geometry.append({
                'gate_index': gate_index,
                'gate': gate,
                'node_x_coords': node_x_coords,
                'diffusion_start': node_x_coords[0] - 25,
                'diffusion_end': node_x_coords[-1] + 25
            })

            # Gate Header Label
            header_x, header_y = self.to_screen(start_x, y_vdd)
            c.create_text(header_x + 5, header_y - 22, text=f"Stick Diagram: {gate_title}", fill="#fab387",
                          font=("Arial", max(9, int(12 * self.zoom)), "bold"), anchor="w")

            # 3. Demarcation Line (Center Dashed Line)
            wx1, wy1 = self.to_screen(start_x, y_well)
            wx2, wy2 = self.to_screen(start_x + gate_width, y_well)
            c.create_line(wx1, wy1, wx2, wy2, fill="#7f849c", width=1, dash=(6, 4))
            c.create_text(wx2 + 65, wy1, text="Demarcation Line", fill="#7f849c", font=("Arial", max(7, int(9 * self.zoom))))

            # 4. Active Diffusion Strips
            px1, py1 = self.to_screen(node_x_coords[0] - 25, y_pdiff)
            px2, py2 = self.to_screen(node_x_coords[-1] + 25, y_pdiff)
            c.create_line(px1, py1, px2, py2, fill=c_pdiff, width=max(8, int(12 * self.zoom)))
            c.create_text(px2 + 30, py1, text="pDIFF", fill="#ffffff", font=("Arial", max(8, int(11 * self.zoom)), "bold"), anchor="w")

            nx1, ny1 = self.to_screen(node_x_coords[0] - 25, y_ndiff)
            nx2, ny2 = self.to_screen(node_x_coords[-1] + 25, y_ndiff)
            c.create_line(nx1, ny1, nx2, ny2, fill=c_ndiff, width=max(8, int(12 * self.zoom)))
            c.create_text(nx2 + 30, ny1, text="nDIFF", fill="#ffffff", font=("Arial", max(8, int(11 * self.zoom)), "bold"), anchor="w")

            # 5. Polysilicon Vertical Gates & Input Labels
            for i, px in enumerate(poly_x_coords):
                lbl = inputs[i]
                sx1, sy1 = self.to_screen(px, y_pdiff - 35)
                sx2, sy2 = self.to_screen(px, y_ndiff + 35)
                c.create_line(sx1, sy1, sx2, sy2, fill=c_poly, width=max(3, int(5 * self.zoom)))
                c.create_text(sx1, sy1 - 12, text=lbl, fill="#ffffff", font=("Arial", max(9, int(12 * self.zoom)), "bold"))

            # 6. Render Source (S) / Drain (D) Labels for ALL pDIFF and nDIFF Nodes
            for i in range(num_nodes):
                nx_val = node_x_coords[i]
                
                # pDIFF S/D Text
                lx, ly = self.to_screen(nx_val, y_pdiff - 16)
                c.create_text(lx, ly, text=p_sd[i], fill=c_sd, font=("Arial", max(8, int(11 * self.zoom)), "bold"))
                
                # nDIFF S/D Text
                lx, ly = self.to_screen(nx_val, y_ndiff + 16)
                c.create_text(lx, ly, text=n_sd[i], fill=c_sd, font=("Arial", max(8, int(11 * self.zoom)), "bold"))

            y_x_coords = []

            # 7. pDIFF Contacts and Metal Connections
            for contact in p_contacts:
                nx_val = node_x_coords[contact['idx']]
                if (gate_index, 'p', contact['idx']) in shared_terminal_indices:
                    continue
                self.draw_contact_cut(nx_val, y_pdiff)
                if contact['type'] == 'VDD':
                    c1, c2 = self.to_screen(nx_val, y_vdd), self.to_screen(nx_val, y_pdiff)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                elif contact['type'] == 'XOR_BRANCH':
                    branch_y = y_vdd + 45
                    c1, c2 = self.to_screen(nx_val, y_pdiff), self.to_screen(nx_val, branch_y)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                elif contact['type'] == 'Y':
                    c1, c2 = self.to_screen(nx_val, y_pdiff), self.to_screen(nx_val, y_well)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                    y_x_coords.append(nx_val)

            # 8. nDIFF Contacts and Metal Connections
            for contact in n_contacts:
                nx_val = node_x_coords[contact['idx']]
                self.draw_contact_cut(nx_val, y_ndiff)
                if contact['type'] == 'GND':
                    c1, c2 = self.to_screen(nx_val, y_ndiff), self.to_screen(nx_val, y_gnd)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                elif contact['type'] == 'GND_M2':
                    # Keep the route on M1 up to GND; use M2 only to cross the rail.
                    y_m1_landing = y_gnd - 15
                    y_underpass = y_gnd + 45
                    c1, c2 = self.to_screen(nx_val, y_ndiff), self.to_screen(nx_val, y_m1_landing)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                    self.draw_contact_cut(nx_val, y_m1_landing)
                    c3 = self.to_screen(nx_val, y_underpass)
                    c.create_line(c2[0], c2[1], c3[0], c3[1], fill=c_metal2, width=max(3, int(4 * self.zoom)))
                    self.draw_contact_cut(nx_val, y_underpass)
                elif contact['type'] == 'Y':
                    c1, c2 = self.to_screen(nx_val, y_ndiff), self.to_screen(nx_val, y_well)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                    y_x_coords.append(nx_val)

            # 9. Output Bus Y Interconnect Routing
            if y_x_coords:
                min_yx = min(y_x_coords)
                max_yx = max(y_x_coords)

                bus_end_x = max(max_yx, node_x_coords[-1] + 65)
                m1, m2 = self.to_screen(min_yx, y_well), self.to_screen(bus_end_x, y_well)
                c.create_line(m1[0], m1[1], m2[0], m2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                c.create_text(m2[0] + 15, m2[1], text="Y", fill="#ffffff", font=("Arial", max(10, int(14 * self.zoom)), "bold"))

            start_x += gate_width + 80

        # Join matching rail terminals so adjacent gates share an active region.
        for left, right in zip(gate_geometry, gate_geometry[1:]):
            left_gate = left['gate']
            right_gate = right['gate']
            left_last_idx = len(left['node_x_coords']) - 1
            left_p_terminal = next(
                (contact['type'] for contact in left_gate['p_contacts'] if contact['idx'] == left_last_idx),
                None
            )
            right_p_terminal = next(
                (contact['type'] for contact in right_gate['p_contacts'] if contact['idx'] == 0),
                None
            )
            if left_p_terminal == right_p_terminal == 'VDD':
                x1, y = self.to_screen(left['diffusion_end'], 150)
                x2, _ = self.to_screen(right['diffusion_start'], 150)
                c.create_line(x1, y, x2, y, fill=c_pdiff, width=max(8, int(12 * self.zoom)))

        # Join the two pull-up branch nodes in the XOR/XNOR layout.
        for geometry in gate_geometry:
            if geometry['gate']['gtype'] not in ('XOR', 'XNOR'):
                continue
            branch_contacts = [
                contact for contact in geometry['gate']['p_contacts']
                if contact['type'] == 'XOR_BRANCH'
            ]
            if len(branch_contacts) == 2:
                node_x = geometry['node_x_coords']
                x1, branch_y = self.to_screen(node_x[branch_contacts[0]['idx']], 105)
                x2, _ = self.to_screen(node_x[branch_contacts[1]['idx']], 105)
                c.create_line(x1, branch_y, x2, branch_y, fill=c_metal, width=max(3, int(4 * self.zoom)))

            underpass_start = self.to_screen(node_x[0], 445)
            underpass_end = self.to_screen(node_x[4], 445)
            c.create_line(
                underpass_start[0], underpass_start[1],
                underpass_end[0], underpass_end[1],
                fill=c_metal, width=max(3, int(4 * self.zoom))
            )
