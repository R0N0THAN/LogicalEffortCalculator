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
        # Separated Inverter Core Model (Inputs: A, A_bar, B, B_bar)
        inputs = ['A', 'A_bar', 'B', 'B_bar']
        p_contacts = [{'idx': 0, 'type': 'VDD'}, {'idx': 2, 'type': 'Y'}, {'idx': 4, 'type': 'VDD'}]
        n_contacts = [{'idx': 0, 'type': 'GND'}, {'idx': 2, 'type': 'Y'}, {'idx': 4, 'type': 'GND'}]
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
        c_poly = "#ef5350"   # Polysilicon Red
        c_pdiff = "#ffca28"  # P-Diff Yellow
        c_ndiff = "#66bb6a"  # N-Diff Green
        c_sd = "#ff7043"     # Source/Drain Orange

        start_x = 80
        for gate in target_gates:
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

            # 1. Power Rails (Metal-1 Blue)
            vx1, vy1 = self.to_screen(start_x, y_vdd)
            vx2, vy2 = self.to_screen(start_x + gate_width, y_vdd)
            c.create_line(vx1, vy1, vx2, vy2, fill=c_metal, width=max(4, int(6 * self.zoom)))
            c.create_text(vx2 + 25, vy1, text="VDD", fill="#ffffff", font=("Arial", max(9, int(12 * self.zoom)), "bold"))

            gx1, gy1 = self.to_screen(start_x, y_gnd)
            gx2, gy2 = self.to_screen(start_x + gate_width, y_gnd)
            c.create_line(gx1, gy1, gx2, gy2, fill=c_metal, width=max(4, int(6 * self.zoom)))
            c.create_text(gx2 + 25, gy1, text="GND", fill="#ffffff", font=("Arial", max(9, int(12 * self.zoom)), "bold"))

            # 2. Gate Header Label
            c.create_text(vx1 + 5, vy1 - 22, text=f"Stick Diagram: {gate_title}", fill="#fab387", 
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
                self.draw_contact_cut(nx_val, y_pdiff)
                if contact['type'] == 'VDD':
                    c1, c2 = self.to_screen(nx_val, y_vdd), self.to_screen(nx_val, y_pdiff)
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
                elif contact['type'] == 'Y':
                    c1, c2 = self.to_screen(nx_val, y_ndiff), self.to_screen(nx_val, y_well)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                    y_x_coords.append(nx_val)

            # 9. Output Bus Y Interconnect Routing
            if y_x_coords:
                min_yx = min(y_x_coords)
                max_yx = max(y_x_coords)
                
                m1, m2 = self.to_screen(min_yx, y_well), self.to_screen(max_yx + 35, y_well)
                c.create_line(m1[0], m1[1], m2[0], m2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                c.create_text(m2[0] + 15, m2[1], text="Y", fill="#ffffff", font=("Arial", max(10, int(14 * self.zoom)), "bold"))

            start_x += gate_width + 80