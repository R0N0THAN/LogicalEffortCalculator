import tkinter as tk
from tkinter import ttk

# Adjust these weights to tune the all-gates placement objective.
# Wire length is measured in diagram units; the other weights reward each
# eligible direct connection and shared VDD or GND diffusion boundary.
GATE_ORDERING_WEIGHTS = {
    'wire_length': 1.0,
    'direct_connections': 250.0,
    'shared_diffusion': 180.0,
}


def _mirror_gate_stick_layout(gate):
    mirrored = dict(gate)
    last_idx = len(gate['inputs'])
    mirrored['inputs'] = list(reversed(gate['inputs']))
    mirrored['p_contacts'] = [
        {**contact, 'idx': last_idx - contact['idx']}
        for contact in gate['p_contacts']
    ]
    mirrored['n_contacts'] = [
        {**contact, 'idx': last_idx - contact['idx']}
        for contact in gate['n_contacts']
    ]
    mirrored['p_sd'] = list(reversed(gate['p_sd']))
    mirrored['n_sd'] = list(reversed(gate['n_sd']))
    mirrored['mirrored'] = True
    return mirrored


def optimize_gate_placement(nodes, wires):
    """Return a locally optimized sequence of (node, mirrored, output_left)."""
    layouts = {node['id']: get_gate_stick_layout(node) for node in nodes}
    node_by_id = {node['id']: node for node in nodes}
    gate_ids = set(node_by_id)
    weights = GATE_ORDERING_WEIGHTS

    def boundary_type(placement, side, contact_group):
        node, mirrored, _ = placement
        layout = layouts[node['id']]
        idx = 0 if side == 'left' else len(layout['inputs'])
        if mirrored:
            idx = len(layout['inputs']) - idx
        return next(
            (
                contact['type']
                for contact in layout[contact_group]
                if contact['idx'] == idx
            ),
            None
        )

    def input_x(gate_start, layout, pin_idx, mirrored):
        physical_pin = len(layout['inputs']) - 1 - pin_idx if mirrored else pin_idx
        return gate_start + 85 + physical_pin * 90

    def output_x(gate_start, layout, output_left):
        if output_left:
            return gate_start - 25
        return gate_start + len(layout['inputs']) * 90 + 105

    input_fanout = {}
    for wire in wires:
        if wire['from_id'] not in gate_ids and wire['to_id'] in gate_ids:
            input_fanout[wire['from_id']] = input_fanout.get(wire['from_id'], 0) + 1

    def score(placement):
        starts = {}
        placement_indices = {}
        cursor = 80
        for index, (node, mirrored, output_left) in enumerate(placement):
            layout = layouts[node['id']]
            starts[node['id']] = (cursor, mirrored, output_left)
            placement_indices[node['id']] = index
            cursor += (len(layout['inputs']) + 1) * 90 + 60 + 80
        rail_end = cursor - 80
        wire_length = 0.0
        direct_connections = 0

        for wire in wires:
            source_id, target_id = wire['from_id'], wire['to_id']
            if target_id not in node_by_id:
                if source_id in starts and wire.get('to_pin') is not None:
                    source_layout = layouts[source_id]
                    source_start, _, source_output_left = starts[source_id]
                    source_index = placement_indices[source_id]
                    sink_x = 35 if source_output_left else rail_end + 45
                    wire_length += abs(
                        output_x(source_start, source_layout, source_output_left) - sink_x
                    )
                    if source_index != (0 if source_output_left else len(placement) - 1):
                        wire_length += 220
                continue

            target_layout = layouts[target_id]
            target_start, target_mirrored, _ = starts[target_id]
            target_pin = wire.get('to_pin', 0)
            target_x = input_x(target_start, target_layout, target_pin, target_mirrored)
            if source_id in starts:
                source_start, _, source_output_left = starts[source_id]
                source_layout = layouts[source_id]
                source_index = placement_indices[source_id]
                target_index = placement_indices[target_id]
                direct = False
                wire_length += abs(
                    output_x(source_start, source_layout, source_output_left) - target_x
                )
                if target_index == source_index + 1 and not source_output_left:
                    direct = target_pin == (
                        len(target_layout['inputs']) - 1 if target_mirrored else 0
                    )
                elif target_index == source_index - 1 and source_output_left:
                    direct = target_pin == (
                        0 if target_mirrored else len(target_layout['inputs']) - 1
                    )
                if direct:
                    span_min, span_max = sorted(
                        (
                            output_x(source_start, source_layout, source_output_left),
                            target_x
                        )
                    )
                    direct = not any(
                        span_min < target_start + 40 + contact['idx'] * 90 < span_max
                        for contact in target_layout['n_contacts']
                        if contact['type'] == 'Y'
                    )
                if direct:
                    direct_connections += 1
                    wire_length += 10
                else:
                    wire_length += 430
            else:
                wire_length += abs((80 - 35) - target_x)
                target_index = placement_indices[target_id]
                is_first_pin = target_pin == (
                    len(target_layout['inputs']) - 1 if target_mirrored else 0
                )
                crosses_output_contact = any(
                    45 < starts[target_id][0] + 40 + contact['idx'] * 90 < target_x
                    for contact in target_layout['n_contacts']
                    if contact['type'] == 'Y'
                )
                if (
                    target_index == 0
                    and is_first_pin
                    and input_fanout.get(source_id) == 1
                    and not crosses_output_contact
                ):
                    wire_length += 10
                else:
                    wire_length += 210

        shared_diffusion = sum(
            (
                boundary_type(left, 'right', 'p_contacts')
                == boundary_type(right, 'left', 'p_contacts')
                == 'VDD'
            ) + (
                boundary_type(left, 'right', 'n_contacts')
                == boundary_type(right, 'left', 'n_contacts')
                == 'GND'
            )
            for left, right in zip(placement, placement[1:])
        )
        return (
            weights['wire_length'] * wire_length
            - weights['direct_connections'] * direct_connections
            - weights['shared_diffusion'] * shared_diffusion
        )

    if not nodes:
        return []

    degree = {node_id: 0 for node_id in gate_ids}
    for wire in wires:
        if wire['from_id'] in gate_ids and wire['to_id'] in gate_ids:
            degree[wire['from_id']] += 1
            degree[wire['to_id']] += 1

    seeds = [
        [(node, False, False) for node in nodes],
        [(node, False, False) for node in reversed(nodes)],
        [
            (node, False, False)
            for node in sorted(nodes, key=lambda item: (-degree[item['id']], item['id']))
        ],
    ]
    best_placement = seeds[0]
    best_score = score(best_placement)

    for seed in seeds:
        current = list(seed)
        current_score = score(current)
        for _ in range(max(4, len(nodes) * 2)):
            best_move = None
            best_move_score = current_score
            size = len(current)
            swap_pairs = (
                ((i, i + 1) for i in range(size - 1))
                if size > 32
                else ((i, j) for i in range(size) for j in range(i + 1, size))
            )
            for i, j in swap_pairs:
                candidate = list(current)
                candidate[i], candidate[j] = candidate[j], candidate[i]
                candidate_score = score(candidate)
                if candidate_score < best_move_score:
                    best_move, best_move_score = candidate, candidate_score
            for i in range(size):
                candidate = list(current)
                node, mirrored, output_left = candidate[i]
                candidate[i] = (node, not mirrored, output_left)
                candidate_score = score(candidate)
                if candidate_score < best_move_score:
                    best_move, best_move_score = candidate, candidate_score
                candidate = list(current)
                candidate[i] = (node, mirrored, not output_left)
                candidate_score = score(candidate)
                if candidate_score < best_move_score:
                    best_move, best_move_score = candidate, candidate_score
            if best_move is None:
                break
            current, current_score = best_move, best_move_score
        if current_score < best_score:
            best_placement, best_score = current, current_score

    return best_placement


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
        self.canvas.create_oval(
            sx - r, sy - r, sx + r, sy + r,
            fill="#ffffff", outline="#11111b", width=2, tags="contact_cut"
        )
        self.canvas.create_oval(
            sx - r + 3, sy - r + 3, sx + r - 3, sy + r - 3,
            fill="#11111b", outline="#11111b", tags="contact_cut"
        )

    def render_stick_diagram(self):
        c = self.canvas
        c.delete("all")

        if not self.logic_nodes:
            c.create_text(400, 250, text="No logic gates found in schematic.", fill="#ffffff", font=("Arial", 12))
            return

        sel_idx = self.gate_combo.current()
        weight_key = tuple(
            (key, GATE_ORDERING_WEIGHTS[key])
            for key in ('wire_length', 'direct_connections', 'shared_diffusion')
        )
        if getattr(self, '_gate_placement_weight_key', None) != weight_key:
            self._gate_placement = optimize_gate_placement(
                self.logic_nodes, self.graph_data.get('wires', [])
            )
            self._gate_placement_weight_key = weight_key
        placement_by_id = {
            node['id']: (mirrored, output_left)
            for node, mirrored, output_left in self._gate_placement
        }
        if sel_idx == 0:
            target_gates = []
            for node, mirrored, output_left in self._gate_placement:
                gate = get_gate_stick_layout(node)
                if mirrored:
                    gate = _mirror_gate_stick_layout(gate)
                gate['output_left'] = output_left
                target_gates.append(gate)
        else:
            node = self.logic_nodes[sel_idx - 1]
            gate = get_gate_stick_layout(node)
            mirrored, output_left = placement_by_id[node['id']]
            if mirrored:
                gate = _mirror_gate_stick_layout(gate)
            gate['output_left'] = output_left
            target_gates = [gate]

        c_metal = "#42a5f5"  # Metal-1 Blue
        c_metal2 = "#ab47bc"  # Metal-2 Purple
        c_poly = "#ef5350"   # Polysilicon Red
        c_pdiff = "#ffca28"  # P-Diff Yellow
        c_ndiff = "#66bb6a"  # N-Diff Green
        c_sd = "#ff7043"     # Source/Drain Orange

        start_x = 80
        layout_start_x = start_x
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
        shared_n_terminal_indices = set()
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
            left_n_terminal = next(
                (contact['type'] for contact in left_gate['n_contacts'] if contact['idx'] == left_last_idx),
                None
            )
            right_n_terminal = next(
                (contact['type'] for contact in right_gate['n_contacts'] if contact['idx'] == 0),
                None
            )
            if left_n_terminal == right_n_terminal == 'GND':
                shared_n_terminal_indices.add((gate_index, 0))

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
                'input_poly_x_coords': (
                    list(reversed(poly_x_coords)) if gate.get('mirrored') else poly_x_coords
                ),
                'mirrored': gate.get('mirrored', False),
                'output_left': gate.get('output_left', False),
                'input_via_y': y_well + 10,
                'input_landing_y': y_gnd - 15,
                'output_x': (
                    node_x_coords[0] - 65
                    if gate.get('output_left')
                    else node_x_coords[-1] + 65
                ),
                'output_y': y_well,
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
                if (gate_index, contact['idx']) in shared_n_terminal_indices:
                    continue
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
                    c.create_line(
                        c2[0], c2[1], c3[0], c3[1],
                        fill=c_metal2, width=max(3, int(4 * self.zoom)), tags="metal2"
                    )
                    self.draw_contact_cut(nx_val, y_underpass)
                elif contact['type'] == 'Y':
                    c1, c2 = self.to_screen(nx_val, y_ndiff), self.to_screen(nx_val, y_well)
                    c.create_line(c1[0], c1[1], c2[0], c2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                    y_x_coords.append(nx_val)

            # 9. Output Bus Y Interconnect Routing
            if y_x_coords:
                min_yx = min(y_x_coords)
                max_yx = max(y_x_coords)

                if gate.get('output_left'):
                    bus_end_x = min(min_yx, node_x_coords[0] - 65)
                    bus_start_x = bus_end_x
                    bus_end_x = max_yx
                else:
                    bus_end_x = max(max_yx, node_x_coords[-1] + 65)
                    bus_start_x = min_yx
                gate_geometry[-1]['output_bus_segment'] = (
                    bus_start_x, bus_end_x, y_well
                )
                m1, m2 = (
                    self.to_screen(bus_start_x, y_well),
                    self.to_screen(bus_end_x, y_well)
                )
                c.create_line(m1[0], m1[1], m2[0], m2[1], fill=c_metal, width=max(3, int(4 * self.zoom)))
                label_x = m1[0] - 15 if gate.get('mirrored') else m2[0] + 15
                c.create_text(
                    label_x, m1[1],
                    text="Y", fill="#ffffff",
                    font=("Arial", max(10, int(14 * self.zoom)), "bold"),
                    anchor="e" if gate.get('mirrored') else "w"
                )

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
            left_n_terminal = next(
                (contact['type'] for contact in left_gate['n_contacts'] if contact['idx'] == left_last_idx),
                None
            )
            right_n_terminal = next(
                (contact['type'] for contact in right_gate['n_contacts'] if contact['idx'] == 0),
                None
            )
            if left_n_terminal == right_n_terminal == 'GND':
                x1, y = self.to_screen(left['diffusion_end'], 310)
                x2, _ = self.to_screen(right['diffusion_start'], 310)
                c.create_line(x1, y, x2, y, fill=c_ndiff, width=max(8, int(12 * self.zoom)))

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

        gate_geometry_by_id = {
            geometry['gate']['node_id']: geometry
            for geometry in gate_geometry
        }
        graph_nodes_by_id = {
            node['id']: node
            for node in self.graph_data['nodes']
        }
        wire_groups = {}

        for wire in self.graph_data.get('wires', []):
            source_id = wire['from_id']
            target_node = graph_nodes_by_id.get(wire['to_id'])
            if target_node and target_node['type'] not in ('INPUT',):
                wire_groups.setdefault(source_id, []).append(wire)

        wire_routes = []
        for source_id, wires in wire_groups.items():
            source_geometry = gate_geometry_by_id.get(source_id)
            target_connections = []
            output_sinks = []
            for wire in wires:
                target_geometry = gate_geometry_by_id.get(wire['to_id'])
                if target_geometry and 0 <= wire['to_pin'] < len(target_geometry['input_poly_x_coords']):
                    target_connections.append((target_geometry, wire['to_pin']))
                elif graph_nodes_by_id.get(wire['to_id'], {}).get('type') == 'OUTPUT':
                    output_sinks.append(graph_nodes_by_id[wire['to_id']])

            if not target_connections and not output_sinks:
                continue

            if source_geometry:
                source_x = source_geometry['output_x']
            else:
                source_x = layout_start_x - 35
            route_xs = [source_x]
            route_xs.extend(
                geometry['input_poly_x_coords'][pin_idx]
                for geometry, pin_idx in target_connections
            )
            if output_sinks:
                route_xs.append(rail_end_x + 45)

            wire_routes.append({
                'source_id': source_id,
                'source_geometry': source_geometry,
                'source_x': source_x,
                'target_connections': target_connections,
                'output_sinks': output_sinks,
                'direct_input_targets': [],
                'direct_output_sinks': [],
                'direct_targets': [],
                'x_min': min(route_xs),
                'x_max': max(route_xs)
            })

        gate_order = {
            geometry['gate']['node_id']: index
            for index, geometry in enumerate(gate_geometry)
        }
        last_gate_index = len(gate_geometry) - 1
        for route in wire_routes:
            source_node = graph_nodes_by_id.get(route['source_id'], {})
            if source_node.get('type') == 'INPUT' and len(route['target_connections']) == 1:
                for target_geometry, pin_idx in route['target_connections']:
                    first_pin = (
                        len(target_geometry['input_poly_x_coords']) - 1
                        if target_geometry['mirrored']
                        else 0
                    )
                    if (
                        gate_order[target_geometry['gate']['node_id']] == 0
                        and pin_idx == first_pin
                        and not any(
                            layout_start_x - 35
                            < target_geometry['node_x_coords'][contact['idx']]
                            < target_geometry['input_poly_x_coords'][pin_idx]
                            for contact in target_geometry['gate']['n_contacts']
                            if contact['type'] == 'Y'
                        )
                    ):
                        route['direct_input_targets'].append((target_geometry, pin_idx))
                direct_input_pins = {
                    (geometry['gate']['node_id'], pin_idx)
                    for geometry, pin_idx in route['direct_input_targets']
                }
                route['target_connections'] = [
                    (geometry, pin_idx)
                    for geometry, pin_idx in route['target_connections']
                    if (geometry['gate']['node_id'], pin_idx) not in direct_input_pins
                ]

            if (
                route['source_geometry']
                and gate_order[route['source_id']] == (
                    0 if route['source_geometry']['output_left'] else last_gate_index
                )
                and route['output_sinks']
            ):
                route['direct_output_sinks'] = route['output_sinks']
                route['output_sinks'] = []

            for target_geometry, pin_idx in route['target_connections']:
                target_index = gate_order[target_geometry['gate']['node_id']]
                is_next_gate = False
                if route['source_geometry']:
                    source_index = gate_order[route['source_id']]
                    if abs(target_index - source_index) == 1:
                        target_is_right = target_index > source_index
                        facing_pin = (
                            len(target_geometry['input_poly_x_coords']) - 1
                            if target_geometry['mirrored'] == target_is_right
                            else 0
                        )
                        source_faces_target = (
                            not route['source_geometry']['output_left']
                            if target_is_right
                            else route['source_geometry']['output_left']
                        )
                        is_next_gate = source_faces_target and pin_idx == facing_pin
                if is_next_gate:
                    route['direct_targets'].append((target_geometry, pin_idx))

        # Gap routes can use progressively higher M1 tracks to avoid risers.
        direct_route_ys = (250, 220, 200, 180, 160, 140, 120, 390)
        direct_candidates = [
            (route, target_geometry, pin_idx)
            for route in wire_routes
            for target_geometry, pin_idx in route['direct_targets']
        ]
        safe_direct_targets = {id(route): [] for route in wire_routes}
        accepted_direct_paths = []
        for route, target_geometry, pin_idx in sorted(
            direct_candidates,
            key=lambda item: (
                abs(
                    item[1]['input_poly_x_coords'][item[2]] - item[0]['source_x']
                ),
                item[0]['source_id']
            )
        ):
            target_x = target_geometry['input_poly_x_coords'][pin_idx]
            span_min, span_max = sorted((route['source_x'], target_x))
            crosses_other_input = any(
                other_route['source_id'] != route['source_id']
                and other_geometry['gate']['node_id'] == target_geometry['gate']['node_id']
                and span_min < other_geometry['input_poly_x_coords'][other_pin] < span_max
                for other_route in wire_routes
                for other_geometry, other_pin in other_route['target_connections']
            )
            crosses_target_output = any(
                span_min < target_geometry['node_x_coords'][contact['idx']] < span_max
                for contact in target_geometry['gate']['n_contacts']
                if contact['type'] == 'Y'
            )
            if crosses_other_input or crosses_target_output:
                continue

            source_y = route['source_geometry']['output_y']
            selected_route = None
            for route_y in direct_route_ys:
                target_y = (
                    target_geometry['input_landing_y']
                    if route_y == 390
                    else route_y
                    if route_y < 230
                    else target_geometry['input_via_y']
                )
                candidate_segments = [
                    ((route['source_x'], source_y), (route['source_x'], route_y)),
                    ((route['source_x'], route_y), (target_x, route_y)),
                    ((target_x, route_y), (target_x, target_y))
                ]

                def intersects(first, second):
                    (x1, y1), (x2, y2) = first
                    (x3, y3), (x4, y4) = second
                    if y1 == y2 and x3 == x4:
                        return min(x1, x2) < x3 < max(x1, x2) and min(y3, y4) < y1 < max(y3, y4)
                    if x1 == x2 and y3 == y4:
                        return min(x3, x4) < x1 < max(x3, x4) and min(y1, y2) < y3 < max(y1, y2)
                    if y1 == y2 == y3 == y4:
                        return y1 == y3 and max(min(x1, x2), min(x3, x4)) < min(max(x1, x2), max(x3, x4))
                    if x1 == x2 == x3 == x4:
                        return x1 == x3 and max(min(y1, y2), min(y3, y4)) < min(max(y1, y2), max(y3, y4))
                    return False

                crosses_output_riser = any(
                    intersects(segment, ((geometry['output_x'], geometry['output_y']),
                                          (geometry['output_x'], geometry['input_landing_y'])))
                    for segment in candidate_segments
                    for geometry in gate_geometry
                    if geometry['gate']['node_id'] != route['source_id']
                )
                crosses_output_bus = any(
                    intersects(segment, ((bus_start, bus_y), (bus_end, bus_y)))
                    for segment in candidate_segments
                    for geometry in gate_geometry
                    for bus_start, bus_end, bus_y in [geometry.get('output_bus_segment', (0, 0, 0))]
                    if bus_start != bus_end
                    and geometry['gate']['node_id'] != route['source_id']
                )
                crosses_other_direct = any(
                    other_source != route['source_id']
                    and any(
                        intersects(segment, other_segment)
                        for segment in candidate_segments
                        for other_segment in other_segments
                    )
                    for other_source, other_segments in accepted_direct_paths
                )
                if not crosses_output_riser and not crosses_output_bus and not crosses_other_direct:
                    selected_route = (route_y, candidate_segments)
                    break

            if selected_route:
                route_y, candidate_segments = selected_route
                safe_direct_targets[id(route)].append((target_geometry, pin_idx))
                route.setdefault('direct_route_lanes', {})[
                    (target_geometry['gate']['node_id'], pin_idx)
                ] = route_y
                accepted_direct_paths.append((route['source_id'], candidate_segments))

        for route in wire_routes:
            route['direct_targets'] = safe_direct_targets[id(route)]
            direct_pin_keys = {
                (geometry['gate']['node_id'], pin_idx)
                for geometry, pin_idx in route['direct_targets']
            }
            remaining_targets = [
                (geometry, pin_idx)
                for geometry, pin_idx in route['target_connections']
                if (geometry['gate']['node_id'], pin_idx) not in direct_pin_keys
            ]
            route['target_connections'] = remaining_targets
            route_xs = [route['source_x']]
            route_xs.extend(
                geometry['input_poly_x_coords'][pin_idx]
                for geometry, pin_idx in remaining_targets
            )
            if route['output_sinks']:
                route_xs.append(rail_end_x + 45)
            route['x_min'] = min(route_xs)
            route['x_max'] = max(route_xs)

        # Reserve the near-demarcation M1 tracks used by direct gate connections.
        track_intervals = {}
        for route in wire_routes:
            for target_geometry, pin_idx in route['direct_targets']:
                target_x = target_geometry['input_poly_x_coords'][pin_idx]
                route_y = route['direct_route_lanes'][
                    (target_geometry['gate']['node_id'], pin_idx)
                ]
                track_intervals.setdefault(route_y, []).append(
                    (min(route['source_x'], target_x), max(route['source_x'], target_x))
                )

        input_via_positions = {
            (geometry['gate']['node_id'], pin_idx): (poly_x, geometry['input_via_y'])
            for geometry in gate_geometry
            for pin_idx, poly_x in enumerate(geometry['input_poly_x_coords'])
        }
        for route in wire_routes:
            for target_geometry, pin_idx in route['direct_targets']:
                route_y = route['direct_route_lanes'][
                    (target_geometry['gate']['node_id'], pin_idx)
                ]
                if route_y < 230:
                    input_via_positions[(target_geometry['gate']['node_id'], pin_idx)] = (
                        target_geometry['input_poly_x_coords'][pin_idx], route_y
                    )
        for poly_x, via_y in input_via_positions.values():
            self.draw_contact_cut(poly_x, via_y)

        # Keep general nets below GND so their M1 runs do not cross gate wiring.
        for route in sorted(
            wire_routes,
            key=lambda item: (-(item['x_max'] - item['x_min']), item['source_id'])
        ):
            if not route['target_connections'] and not route['output_sinks']:
                continue
            lane_y = 450
            while not all(
                route['x_max'] + 12 <= start or end + 12 <= route['x_min']
                for start, end in track_intervals.get(lane_y, [])
            ):
                lane_y += 24
            route['lane_y'] = lane_y
            track_intervals.setdefault(lane_y, []).append((route['x_min'], route['x_max']))

        direct_source_stems = set()
        routes_with_general_branches = {
            route['source_id']
            for route in wire_routes
            if route['target_connections'] or route['output_sinks']
        }
        for route in wire_routes:
            source_geometry = route['source_geometry']
            source_x = route['source_x']
            for target_geometry, pin_idx in route['direct_input_targets']:
                target_x = target_geometry['input_poly_x_coords'][pin_idx]
                input_y = target_geometry['input_via_y']
                source_start = self.to_screen(layout_start_x - 35, input_y)
                target_end = self.to_screen(target_x, input_y)
                c.create_line(
                    source_start[0], source_start[1],
                    target_end[0], target_end[1],
                    fill=c_metal, width=max(3, int(4 * self.zoom))
                )
                source_node = graph_nodes_by_id.get(route['source_id'], {})
                label_x, label_y = self.to_screen(layout_start_x - 47, input_y)
                c.create_text(
                    label_x, label_y,
                    text=source_node.get('name', f"IN{route['source_id']}"),
                    fill="#ffffff", font=("Arial", max(8, int(10 * self.zoom)), "bold"),
                    anchor="e"
                )

            if route['direct_output_sinks']:
                output_x = source_geometry['output_x']
                output_y = source_geometry['output_y']
                output_end_x = (
                    layout_start_x - 45
                    if source_geometry['output_left']
                    else rail_end_x + 45
                )
                start = self.to_screen(output_x, output_y)
                end = self.to_screen(output_end_x, output_y)
                c.create_line(
                    start[0], start[1], end[0], end[1],
                    fill=c_metal, width=max(3, int(4 * self.zoom))
                )
                label_x, label_y = self.to_screen(
                    output_end_x - 12 if source_geometry['output_left'] else output_end_x + 12,
                    output_y
                )
                c.create_text(
                    label_x, label_y,
                    text=", ".join(
                        sink.get('name', f"OUT{sink['id']}")
                        for sink in route['direct_output_sinks']
                    ),
                    fill="#ffffff", font=("Arial", max(8, int(10 * self.zoom)), "bold"),
                    anchor="e" if source_geometry['output_left'] else "w"
                )

            for target_geometry, pin_idx in route['direct_targets']:
                target_x = target_geometry['input_poly_x_coords'][pin_idx]
                route_y = route['direct_route_lanes'][
                    (target_geometry['gate']['node_id'], pin_idx)
                ]
                source_start = self.to_screen(source_x, source_geometry['output_y'])
                source_corner = self.to_screen(source_x, route_y)
                target_corner = self.to_screen(target_x, route_y)
                target_via_y = (
                    route_y if route_y < 230 else target_geometry['input_via_y']
                )
                target_via = self.to_screen(target_x, target_via_y)
                source_id = route['source_id']
                if (
                    source_id not in direct_source_stems
                    and source_id not in routes_with_general_branches
                ):
                    c.create_line(
                        source_start[0], source_start[1],
                        source_corner[0], source_corner[1],
                        fill=c_metal, width=max(3, int(4 * self.zoom))
                    )
                direct_source_stems.add(route['source_id'])
                c.create_line(
                    source_corner[0], source_corner[1],
                    target_corner[0], target_corner[1],
                    fill=c_metal, width=max(3, int(4 * self.zoom))
                )
                c.create_line(
                    target_corner[0], target_corner[1],
                    target_via[0], target_via[1],
                    fill=c_metal, width=max(3, int(4 * self.zoom))
                )
            if not route['target_connections'] and not route['output_sinks']:
                continue

            lane_y = route['lane_y']
            route_xs = [source_x]

            if source_geometry:
                source_top = self.to_screen(source_x, source_geometry['output_y'])
                source_landing_y = (
                    source_geometry['output_y']
                    if lane_y <= 292
                    else source_geometry['input_landing_y']
                )
                source_landing = self.to_screen(source_x, source_landing_y)
                c.create_line(
                    source_top[0], source_top[1], source_landing[0], source_landing[1],
                    fill=c_metal, width=max(3, int(4 * self.zoom))
                )
                if lane_y > 292:
                    self.draw_contact_cut(source_x, source_geometry['input_landing_y'])
            elif not route['direct_input_targets']:
                source_node = graph_nodes_by_id.get(route['source_id'], {})
                label_x, label_y = self.to_screen(source_x - 12, lane_y)
                c.create_text(
                    label_x, label_y, text=source_node.get('name', f"IN{route['source_id']}"),
                    fill="#ffffff", font=("Arial", max(8, int(10 * self.zoom)), "bold"),
                    anchor="e"
                )

            for target_geometry, pin_idx in route['target_connections']:
                poly_x = target_geometry['input_poly_x_coords'][pin_idx]
                landing_y = target_geometry['input_landing_y']
                landing = self.to_screen(poly_x, landing_y)
                track = self.to_screen(poly_x, lane_y)
                via = self.to_screen(poly_x, target_geometry['input_via_y'])
                c.create_line(
                    via[0], via[1], landing[0], landing[1],
                    fill=c_metal, width=max(3, int(4 * self.zoom))
                )
                c.create_line(
                    landing[0], landing[1], track[0], track[1],
                    fill=c_metal2, width=max(3, int(4 * self.zoom)), tags="metal2"
                )
                self.draw_contact_cut(poly_x, target_geometry['input_landing_y'])
                self.draw_contact_cut(poly_x, lane_y)
                route_xs.append(poly_x)

            if route['output_sinks']:
                output_x = rail_end_x + 45
                route_xs.append(output_x)
                label_x, label_y = self.to_screen(output_x + 12, lane_y)
                c.create_text(
                    label_x, label_y,
                    text=", ".join(
                        sink.get('name', f"OUT{sink['id']}")
                        for sink in route['output_sinks']
                    ),
                    fill="#ffffff", font=("Arial", max(8, int(10 * self.zoom)), "bold"),
                    anchor="w"
                )

            track_start = self.to_screen(min(route_xs), lane_y)
            track_end = self.to_screen(max(route_xs), lane_y)
            c.create_line(
                track_start[0], track_start[1], track_end[0], track_end[1],
                fill=c_metal, width=max(3, int(4 * self.zoom))
            )

            if source_geometry:
                source_landing_y = (
                    source_geometry['output_y']
                    if lane_y <= 292
                    else source_geometry['input_landing_y']
                )
                source_landing = self.to_screen(source_x, source_landing_y)
                source_track = self.to_screen(source_x, lane_y)
                c.create_line(
                    source_landing[0], source_landing[1], source_track[0], source_track[1],
                    fill=c_metal2,
                    width=max(3, int(4 * self.zoom)), tags="metal2"
                )
                self.draw_contact_cut(source_x, lane_y)

        c.tag_raise("metal2")
        c.tag_raise("contact_cut")
