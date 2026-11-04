import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import math
import copy
import heapq

# =====================================================================
# STAGE NUMBER COMPUTATION HELPER (Logic Gates Only)
# =====================================================================
def compute_stage_numbers(nodes, wires):
    in_edges = {nid: [] for nid in nodes}
    for w in wires:
        if w['to_id'] in in_edges:
            in_edges[w['to_id']].append(w['from_id'])

    stage = {}
    for nid, n in nodes.items():
        if n['type'] == 'INPUT':
            stage[nid] = 0

    changed = True
    iterations = 0
    while changed and iterations < 100:
        iterations += 1
        changed = False
        for nid, n in nodes.items():
            # OUTPUT pins and INPUT pins are not logic stages
            if n['type'] in ('INPUT', 'OUTPUT'):
                continue
            preds = in_edges[nid]
            if preds and all(p in stage for p in preds):
                max_pred_stage = max(stage[p] for p in preds)
                new_stage = max_pred_stage + 1
                if stage.get(nid) != new_stage:
                    stage[nid] = new_stage
                    changed = True

    # Assign default Stage 1 for any uncalculated or disconnected logic gates
    for nid, n in nodes.items():
        if n['type'] not in ('INPUT', 'OUTPUT') and nid not in stage:
            stage[nid] = 1

    return stage


# =====================================================================
# PATH SIMPLIFICATION HELPER (Merges Collinear Grid Points)
# =====================================================================
def simplify_path(path):
    if len(path) <= 2:
        return path
    simplified = [path[0]]
    for i in range(1, len(path) - 1):
        prev = simplified[-1]
        curr = path[i]
        nxt = path[i+1]
        dx1, dy1 = curr[0] - prev[0], curr[1] - prev[1]
        dx2, dy2 = nxt[0] - curr[0], nxt[1] - curr[1]
        if (dx1 == 0 and dx2 == 0) or (dy1 == 0 and dy2 == 0):
            continue
        simplified.append(curr)
    simplified.append(path[-1])
    return simplified

# =====================================================================
# ITERATIVE LOGICAL EFFORT CALCULATION ENGINE (Topological Pin Sizing)
# =====================================================================
def calculate_logical_effort(graph_data, manual_path_index=0, custom_graphical_path=None):
    nodes = {n['id']: n for n in graph_data['nodes']}
    wires = graph_data['wires']

    stage_map = compute_stage_numbers(nodes, wires)

    logic_nodes = [n for n in graph_data['nodes'] if n['type'] not in ('INPUT', 'OUTPUT')]
    output_nodes = [n for n in graph_data['nodes'] if n['type'] == 'OUTPUT']
    input_nodes = [n for n in graph_data['nodes'] if n['type'] == 'INPUT']

    empty_summary = {
        "pre_sizing_D": 0.0,
        "ideal_D": 0.0,
        "actual_D": 0.0,
        "N_opt": 0.0,
        "N_opt_int": 0,
        "critical_full_path": []
    }
    if not logic_nodes:
        return empty_summary, "No logic gates found in schematic.", {}, ["[Auto: No paths found]"]

    out_edges = {n['id']: [] for n in graph_data['nodes']}
    in_edges = {n['id']: [] for n in graph_data['nodes']}
    for w in wires:
        out_edges[w['from_id']].append((w['to_id'], w['to_pin']))
        in_edges[w['to_id']].append((w['from_id'], w['to_pin']))

    def get_gate_info(gtype, n_in):
        if gtype == 'INV':
            return 1.0, 1.0, 3.0, 2.0, 1.0
        elif gtype == 'NAND':
            return (n_in + 2) / 3.0, float(n_in), float(n_in + 2), 2.0, float(n_in)
        elif gtype == 'NOR':
            return (2 * n_in + 1) / 3.0, float(n_in), float(2 * n_in + 1), float(n_in), 1.0
        elif gtype in ('XOR', 'XNOR'):
            return 2.0, float(n_in), 6.0, 4.0, 2.0
        return 1.0, 1.0, 3.0, 2.0, 1.0

    def get_pin_cin(node_id, gate_cin):
        node = nodes[node_id]
        if node['type'] == 'OUTPUT':
            return float(node.get('cl', 120.0))
        elif node['type'] == 'INPUT':
            return gate_cin
        return gate_cin

    start_nodes = input_nodes if input_nodes else [n for n in logic_nodes if not in_edges[n['id']]]
    if not start_nodes and logic_nodes:
        start_nodes = [logic_nodes[0]]
        
    end_nodes = output_nodes if output_nodes else [n for n in logic_nodes if not out_edges[n['id']]]
    if not end_nodes and logic_nodes:
        end_nodes = [logic_nodes[-1]]

    def find_paths(curr_id, end_id, path):
        path = path + [curr_id]
        if curr_id == end_id:
            return [path]
        paths = []
        for nxt_id, _ in out_edges[curr_id]:
            if nxt_id not in path:
                paths.extend(find_paths(nxt_id, end_id, path))
        return paths

    all_raw_paths = []
    for s in start_nodes:
        for e in end_nodes:
            all_raw_paths.extend(find_paths(s['id'], e['id'], []))

    if not all_raw_paths:
        all_raw_paths = [[n['id'] for n in logic_nodes]]

    current_cin = {}
    for nid, node in nodes.items():
        if node['type'] not in ('INPUT', 'OUTPUT'):
            current_cin[nid] = float(node['size'])

    # Branching effort is the total successor logical effort normalized by
    # the logical effort of the successor on the selected path.
    def compute_topological_stage_branching(nid, next_on_path_id):
        succ_ids = {sid for sid, _ in out_edges[nid] if nodes[sid]['type'] != 'OUTPUT'}
        if not succ_ids or next_on_path_id not in succ_ids:
            return 1.0

        total_g = sum(
            get_gate_info(nodes[sid]['type'], nodes[sid]['inputs'])[0]
            for sid in succ_ids
        )
        on_path_g = get_gate_info(
            nodes[next_on_path_id]['type'], nodes[next_on_path_id]['inputs']
        )[0]
        return total_g / on_path_g if on_path_g > 0 else 1.0

    def format_path_string(path_ids):
        formatted = []
        for nid in path_ids:
            n = nodes[nid]
            if n['type'] == 'INPUT':
                formatted.append(f"{n.get('name', 'IN')}")
            elif n['type'] == 'OUTPUT':
                formatted.append(f"{n.get('name', 'OUT')} ({n.get('cl', 120)}C)")
            else:
                formatted.append(f"{n.get('name', n['type'])}[S{stage_map.get(nid, '?')}]")
        return " -> ".join(formatted)

    evaluated_paths = []
    for p in all_raw_paths:
        logic_p = [nid for nid in p if nodes[nid]['type'] not in ('INPUT', 'OUTPUT')]
        N_p = len(logic_p)
        if N_p == 0:
            continue

        end_node = nodes[p[-1]]
        c_load_p = float(end_node['cl']) if end_node['type'] == 'OUTPUT' else 120.0

        G_p, P_p = 1.0, 0.0
        for nid in logic_p:
            g, p_val, _, _, _ = get_gate_info(nodes[nid]['type'], nodes[nid]['inputs'])
            G_p *= g
            P_p += p_val

        B_p = 1.0
        for idx, nid in enumerate(logic_p):
            if idx + 1 < len(logic_p):
                next_on_path_id = logic_p[idx + 1]
                b_i = compute_topological_stage_branching(nid, next_on_path_id)
            else:
                b_i = 1.0
            B_p *= b_i

        c_in_first_pin = get_pin_cin(logic_p[0], current_cin[logic_p[0]]) if logic_p else 1.0
        H_p = c_load_p / c_in_first_pin if c_in_first_pin > 0 else 1.0
        F_p = G_p * B_p * H_p
        f_hat_p = F_p ** (1.0 / N_p) if N_p > 0 else 0
        D_ideal_p = N_p * f_hat_p + P_p if N_p > 0 else 0.0

        path_str = format_path_string(p)

        evaluated_paths.append({
            'full_path': p, 'logic_path': logic_p, 'path_str': path_str,
            'D_ideal': D_ideal_p, 'F': F_p, 'G': G_p, 'B': B_p, 'H': H_p, 'P': P_p, 'N': N_p,
            'c_load': c_load_p
        })

    evaluated_paths.sort(key=lambda x: x['D_ideal'], reverse=True)

    path_options = ["[Auto: Worst Delay] " + evaluated_paths[0]['path_str'] + f" ({evaluated_paths[0]['D_ideal']:.2f}τ)"]
    for idx, ep in enumerate(evaluated_paths):
        path_options.append(f"Path {idx+1}: {ep['path_str']} (D = {ep['D_ideal']:.2f}τ)")

    if custom_graphical_path:
        matched_ep = next((ep for ep in evaluated_paths if ep['full_path'] == custom_graphical_path), None)
        if matched_ep:
            target_eval = matched_ep
            selection_mode = "GRAPHICALLY DRAWN CUSTOM PATH"
            custom_option_str = f"[Graphical Custom] {target_eval['path_str']} (D = {target_eval['D_ideal']:.2f}τ)"
            path_options.insert(1, custom_option_str)
        else:
            p = custom_graphical_path
            logic_p = [nid for nid in p if nodes[nid]['type'] not in ('INPUT', 'OUTPUT')]
            N_p = len(logic_p)
            end_node = nodes[p[-1]]
            c_load_p = float(end_node['cl']) if end_node['type'] == 'OUTPUT' else 120.0

            G_p, P_p = 1.0, 0.0
            for nid in logic_p:
                g, p_val, _, _, _ = get_gate_info(nodes[nid]['type'], nodes[nid]['inputs'])
                G_p *= g
                P_p += p_val

            B_p = 1.0
            for idx, nid in enumerate(logic_p):
                if idx + 1 < len(logic_p):
                    next_on_path_id = logic_p[idx + 1]
                    b_i = compute_topological_stage_branching(nid, next_on_path_id)
                else:
                    b_i = 1.0
                B_p *= b_i

            c_in_first_pin = get_pin_cin(logic_p[0], current_cin[logic_p[0]]) if logic_p else 1.0
            H_p = c_load_p / c_in_first_pin if c_in_first_pin > 0 else 1.0
            F_p = G_p * B_p * H_p
            f_hat_p = F_p ** (1.0 / N_p) if N_p > 0 else 0
            D_ideal_p = N_p * f_hat_p + P_p if N_p > 0 else 0.0

            path_str = format_path_string(p)

            target_eval = {
                'full_path': p, 'logic_path': logic_p, 'path_str': path_str,
                'D_ideal': D_ideal_p, 'F': F_p, 'G': G_p, 'B': B_p, 'H': H_p,
                'P': P_p, 'N': N_p, 'c_load': c_load_p
            }
            selection_mode = "GRAPHICALLY DRAWN CUSTOM PATH"
            custom_option_str = f"[Graphical Custom] {path_str} (D = {D_ideal_p:.2f}τ)"
            path_options.insert(1, custom_option_str)
    elif manual_path_index > 0 and manual_path_index <= len(evaluated_paths):
        target_eval = evaluated_paths[manual_path_index - 1]
        selection_mode = f"MANUALLY SELECTED (Path #{manual_path_index})"
    else:
        target_eval = evaluated_paths[0]
        selection_mode = "AUTO-SELECTED (Worst Pre-sizing Delay Path)"

    critical_logic_path = target_eval['logic_path']
    critical_full_path = target_eval['full_path']
    N = target_eval['N']
    c_load = target_eval['c_load']

    direct_input_gate_ids = {
        nid for nid in nodes
        if nodes[nid]['type'] not in ('INPUT', 'OUTPUT')
        and any(nodes[pid]['type'] == 'INPUT' for pid, _ in in_edges[nid])
    }

    in_degree = {nid: len(in_edges[nid]) for nid in nodes}
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    topo_order = []
    while queue:
        curr = queue.pop(0)
        topo_order.append(curr)
        for nxt, _ in out_edges[curr]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    for nid in nodes:
        if nid not in topo_order:
            topo_order.append(nid)

    rev_topo_logic_nodes = [nid for nid in reversed(topo_order) if nodes[nid]['type'] not in ('INPUT', 'OUTPUT')]

    max_iters = 500
    converged = False
    oscillation_resolved = False
    iters_run = 0
    G, B, H, F, P = (target_eval[key] for key in ('G', 'B', 'H', 'F', 'P'))
    f_hat_target = F ** (1.0 / N) if N > 0 else 0.0
    ideal_D = target_eval['D_ideal']
    fixed_input_cin = {nid: current_cin[nid] for nid in direct_input_gate_ids}
    sizing_history = []

    def get_gate_output_cap(nid, cin_values):
        output_cap = 0.0
        for sid, _ in out_edges[nid]:
            if nodes[sid]['type'] == 'OUTPUT':
                output_cap += float(nodes[sid].get('cl', 120.0))
            else:
                output_cap += get_pin_cin(sid, cin_values.get(sid, current_cin[sid]))
        return output_cap if output_cap > 0 else c_load

    def get_path_stage_efforts(cin_values):
        stage_efforts = []
        for nid in critical_logic_path:
            g = get_gate_info(nodes[nid]['type'], nodes[nid]['inputs'])[0]
            input_cap = get_pin_cin(nid, cin_values[nid])
            output_cap = get_gate_output_cap(nid, cin_values)
            stage_efforts.append(g * output_cap / input_cap if input_cap > 0 else 0.0)
        return stage_efforts

    for iteration in range(1, max_iters + 1):
        iters_run = iteration
        new_cin = {}
        stage_f_hat = {stage_map[nid]: f_hat_target for nid in critical_logic_path}
        for nid in rev_topo_logic_nodes:
            node = nodes[nid]
            g, _, u_cin, _, _ = get_gate_info(node['type'], node['inputs'])

            if nid in direct_input_gate_ids:
                new_cin[nid] = fixed_input_cin[nid]
            else:
                output_cap = get_gate_output_cap(nid, new_cin)
                gate_f_hat = stage_f_hat.get(stage_map.get(nid), f_hat_target)
                raw_gate_cin = (g * output_cap / gate_f_hat) if gate_f_hat > 0 else current_cin[nid]
                x = max(1, round(raw_gate_cin / u_cin))
                new_cin[nid] = float(x * u_cin)

        stage_efforts = get_path_stage_efforts(new_cin)
        rounded_F = math.prod(stage_efforts)
        new_f_hat = rounded_F ** (1.0 / N) if N > 0 and rounded_F > 0 else 0.0
        ideal_D = N * new_f_hat + P

        if math.isclose(new_f_hat, f_hat_target, rel_tol=1e-6, abs_tol=1e-6):
            current_cin = new_cin
            converged = True
            break

        state = tuple(new_cin[nid] for nid in rev_topo_logic_nodes)
        if len(sizing_history) >= 2 and state == sizing_history[-2][0] and state != sizing_history[-1][0]:
            previous_effort, previous_cin = sizing_history[-1][1], sizing_history[-1][2]
            if rounded_F < previous_effort:
                current_cin = new_cin
            else:
                current_cin = previous_cin
            oscillation_resolved = True
            break

        sizing_history.append((state, rounded_F, new_cin.copy()))
        current_cin = new_cin
        f_hat_target = new_f_hat

    final_stage_f = get_path_stage_efforts(current_cin)
    rounded_F = math.prod(final_stage_f)
    f_hat_rounded = rounded_F ** (1.0 / N) if N > 0 and rounded_F > 0 else 0.0
    ideal_D = N * f_hat_rounded + P
    actual_D = sum(final_stage_f) + P

    p_avg = P / N if N > 0 else 1.0
    def solve_optimal_f_hat(p_val):
        f_val = 3.6
        for _ in range(50):
            val = p_val + f_val - f_val * math.log(f_val)
            deriv = -math.log(f_val)
            if abs(deriv) < 1e-9:
                break
            diff = val / deriv
            f_val -= diff
            if abs(diff) < 1e-6:
                break
        return max(1.001, f_val)

    f_hat_opt = solve_optimal_f_hat(p_avg)
    N_opt = math.log(rounded_F) / math.log(f_hat_opt) if (rounded_F > 0 and f_hat_opt > 1.0) else N
    N_opt_int = round(N_opt)

    summary = {
        "pre_sizing_D": target_eval['D_ideal'],
        "ideal_D": ideal_D,
        "actual_D": actual_D,
        "N_opt": N_opt,
        "N_opt_int": N_opt_int,
        "critical_full_path": critical_full_path
    }

    lines = []
    lines.append("=== LOGICAL EFFORT EVALUATION ENGINE ===")
    lines.append(f"Target Path Selection Mode: {selection_mode}")

    lines.append("\nALL DETECTED PATHS (Ranked by Pre-Sizing Delay):")
    for idx, ep in enumerate(evaluated_paths):
        is_active = " [SELECTED FOR SIZING]" if ep['full_path'] == critical_full_path else ""
        lines.append(f"  Path #{idx+1}: {ep['path_str']}")
        lines.append(f"          Est Delay D_ideal = {ep['D_ideal']:.3f} tau | Total Effort F = {ep['F']:.2f}{is_active}")

    lines.append(f"\n--- SIZING FOR SELECTED PATH ---")
    lines.append(f"1. Logic Stages (N): {N}")
    path_names = [f"Gate #{nid} [{nodes[nid].get('name', nodes[nid]['type'])}, Stage {stage_map.get(nid, '?')}]" for nid in critical_logic_path]
    lines.append(f"2. Logic Gates Path: {' -> '.join(path_names)}")

    lines.append(f"\n3. Convergence:")
    sizing_status = (
        "OSCILLATION RESOLVED (LOWER-EFFORT STATE)"
        if oscillation_resolved
        else "CONVERGED" if converged else "MAX ITERS REACHED"
    )
    lines.append(f"   Iterative Sizing Status : {sizing_status}")
    if oscillation_resolved:
        lines.append("   Two-state cycle detected; selected the state with lower total path effort.")
    lines.append(f"   Total Iterations        : {iters_run}")

    lines.append("\n4. Final Path Efforts & Branching:")
    lines.append(f"   Path Logical Effort G   = {G:.3f}")
    lines.append(f"   Path Branching Effort B = {B:.3f}")
    lines.append(f"   Path Electrical Effort H = {H:.3f}")
    lines.append(f"   Initial Path Effort F   = G * B * H = {F:.3f}")

    lines.append("\n5. Path Delays:")
    lines.append(f"   Rounded Path Effort F   = {rounded_F:.3f}")
    lines.append(f"   Rounded f_hat           = {f_hat_rounded:.3f}")
    lines.append(f"   IDEAL PATH DELAY D_ideal = {ideal_D:.3f} tau")
    for idx, nid in enumerate(critical_logic_path):
        lines.append(f"   Stage {stage_map.get(nid, '?')} Effort (f_{idx+1}) = {final_stage_f[idx]:.3f}")
    lines.append(f"   Total Parasitic Delay P  = {P:.3f}")
    lines.append(f"   ACTUAL PATH DELAY D      = {actual_D:.3f} tau")

    lines.append("\n6. Final Transistor Widths & Rounded Input Capacitances (Cin):")
    all_logic_ids = sorted(
        critical_logic_path + [n['id'] for n in logic_nodes if n['id'] not in critical_logic_path],
        key=lambda nid: (stage_map.get(nid, 0), nid)
    )
    for nid in all_logic_ids:
        node = nodes[nid]
        c_val = current_cin.get(nid, float(node['size']))
        lock_str = " [INPUT-DRIVEN, FIXED]" if nid in direct_input_gate_ids else ""
        stg = stage_map.get(nid, '?')
        lines.append(f"   Stage {stg} | Gate #{nid} [{node.get('name', node['type'])}]: Cin = {c_val:.1f} C{lock_str}")

    lines.append("\n7. OPTIMAL STAGE COUNT TUNING (N_opt):")
    lines.append(f"   Avg Parasitic p_avg = {p_avg:.3f}")
    lines.append(f"   Optimal Stage Effort (f_hat_opt) = {f_hat_opt:.3f}")
    lines.append(f"   Calculated N_opt = log_(f_hat_opt)(F) = {N_opt:.2f} stages")
    lines.append(f"   RECOMMENDED N_opt = {N_opt_int} stages")

    return summary, "\n".join(lines), current_cin, path_options

# =====================================================================
# TRUTH TABLE GENERATOR
# =====================================================================
def generate_truth_table(graph_data):
    nodes = {n['id']: n for n in graph_data['nodes']}
    wires = graph_data['wires']

    input_nodes = [n for n in graph_data['nodes'] if n['type'] == 'INPUT']
    output_nodes = [n for n in graph_data['nodes'] if n['type'] == 'OUTPUT']

    if not input_nodes or not output_nodes:
        return "Truth table unavailable: Need at least 1 Input and 1 Output node."

    input_nodes.sort(key=lambda n: n.get('name', f"IN_{n['id']}"))
    output_nodes.sort(key=lambda n: n.get('name', f"OUT_{n['id']}"))
    num_inputs = len(input_nodes)
    if num_inputs > 8:
        return "Truth table suppressed (>8 inputs)."

    inputs_to = {n['id']: {} for n in graph_data['nodes']}
    for w in wires:
        inputs_to[w['to_id']][w['to_pin']] = w['from_id']

    headers = [n.get('name', f"IN_{n['id']}") for n in input_nodes] + [n.get('name', f"OUT_{n['id']}") for n in output_nodes]
    table_lines = [" | ".join(f"{h:^7}" for h in headers)]
    table_lines.append("-" * len(table_lines[0]))

    node_vals = {n['id']: False for n in graph_data['nodes']}

    for i in range(1 << num_inputs):
        for idx, in_node in enumerate(input_nodes):
            bit = (i >> (num_inputs - 1 - idx)) & 1
            node_vals[in_node['id']] = bool(bit)

        for _ in range(50):
            changed = False
            for nid, node in nodes.items():
                gtype = node['type']
                if gtype == 'INPUT':
                    continue

                if gtype == 'OUTPUT':
                    src = inputs_to[nid].get(0)
                    val = node_vals[src] if src is not None else False
                else:
                    n_in = node['inputs']
                    in_vals = [node_vals.get(inputs_to[nid].get(p), False) for p in range(n_in)]

                    if gtype == 'INV':
                        val = not in_vals[0]
                    elif gtype == 'NAND':
                        val = not all(in_vals)
                    elif gtype == 'NOR':
                        val = not any(in_vals)
                    elif gtype == 'XOR':
                        if n_in == 4:
                            val = (in_vals[0] and in_vals[3]) or (in_vals[1] and in_vals[2])
                        else:
                            val = (sum(in_vals) % 2) == 1
                    elif gtype == 'XNOR':
                        if n_in == 4:
                            val = (in_vals[0] and in_vals[2]) or (in_vals[1] and in_vals[3])
                        else:
                            val = (sum(in_vals) % 2) == 0
                    else:
                        val = False

                if node_vals[nid] != val:
                    node_vals[nid] = val
                    changed = True

            if not changed:
                break

        in_bits = [str((i >> (num_inputs - 1 - idx)) & 1) for idx in range(num_inputs)]
        out_bits = [str(1 if node_vals[n['id']] else 0) for n in output_nodes]
        row_vals = in_bits + out_bits
        table_lines.append(" | ".join(f"{v:^7}" for v in row_vals))

    return "\n".join(table_lines)


# =====================================================================
# TRANSISTOR SCHEMATIC POPUP WINDOW
# =====================================================================
class TransistorSchematicWindow(tk.Toplevel):
    def __init__(self, parent, node, stage_num=None):
        super().__init__(parent)
        self.node = node
        gtype = node['type']
        n_in = node['inputs']
        cin_val = node['size']
        node_name = node.get('name', f"{gtype}{node['id']}")
        stage_str = f" | Stage {stage_num}" if stage_num is not None else ""
        self.rail_bottom = 520
        if gtype == 'NAND':
            nmos_start_y = 250
            nmos_step = 50
            self.rail_bottom = max(self.rail_bottom, nmos_start_y + (n_in - 1) * nmos_step + 65)
        elif gtype == 'NOR':
            pmos_start_y = 80
            pmos_step = 62
            last_pmos_y = pmos_start_y + (n_in - 1) * pmos_step
            nmos_y = max(380, last_pmos_y + 110)
            self.rail_bottom = max(self.rail_bottom, nmos_y + 100)
        
        self.title(f"Transistor Schematic - Gate {node_name} ({gtype})")
        self.geometry(f"860x{max(680, self.rail_bottom + 150)}")
        self.configure(bg="#11111b")

        ttk.Label(self, text=f"CMOS Transistor Level Schematic for Gate {node_name}{stage_str}", 
                  font=("Arial", 12, "bold")).pack(pady=10)

        info_str = f"Gate Type: {gtype} | Inputs: {n_in} | Stage: {stage_num if stage_num is not None else 'N/A'} | Rounded Cin = {cin_val:.1f} C"
        if gtype in ('XOR', 'XNOR'):
            info_str += " [SEPARATED INVERTERS MODEL]"

        ttk.Label(self, text=info_str, font=("Arial", 10)).pack(pady=(0, 10))

        self.canvas = tk.Canvas(self, bg="#1e1e2e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        self.draw_cmos_schematic()

    def draw_pmos(self, x, y, width_val, label):
        c = self.canvas
        c.create_line(x-15, y-20, x-15, y+20, fill="#f38ba8", width=3)
        c.create_line(x-5, y-20, x-5, y+20, fill="#f38ba8", width=2)
        c.create_oval(x-25, y-4, x-17, y+4, outline="#f38ba8", width=2)
        c.create_line(x-35, y, x-25, y, fill="#f38ba8", width=2)
        c.create_line(x-5, y-15, x+15, y-15, fill="#f38ba8", width=2)
        c.create_line(x-5, y+15, x+15, y+15, fill="#f38ba8", width=2)
        c.create_text(x+22, y-5, text=f"{label}", fill="#cdd6f4", font=("Arial", 8, "bold"), anchor="w")
        c.create_text(x+22, y+8, text=f"W_p={round(width_val)}x", fill="#a6e3a1", font=("Arial", 8), anchor="w")

    def draw_nmos(self, x, y, width_val, label):
        c = self.canvas
        c.create_line(x-15, y-20, x-15, y+20, fill="#89b4fa", width=3)
        c.create_line(x-5, y-20, x-5, y+20, fill="#89b4fa", width=2)
        c.create_line(x-35, y, x-15, y, fill="#89b4fa", width=2)
        c.create_line(x-5, y-15, x+15, y-15, fill="#89b4fa", width=2)
        c.create_line(x-5, y+15, x+15, y+15, fill="#89b4fa", width=2)
        c.create_text(x+22, y-5, text=f"{label}", fill="#cdd6f4", font=("Arial", 8, "bold"), anchor="w")
        c.create_text(x+22, y+8, text=f"W_n={round(width_val)}x", fill="#a6e3a1", font=("Arial", 8), anchor="w")

    def draw_cmos_schematic(self):
        c = self.canvas
        c.delete("all")
        
        gtype = self.node['type']
        n_in = self.node['inputs']
        cin_val = self.node['size']

        u_cin = 3.0 if gtype == 'INV' else (n_in + 2.0 if gtype == 'NAND' else (2.0 * n_in + 1.0 if gtype == 'NOR' else 6.0))
        x_scale = max(1, round(cin_val / u_cin))

        c.create_line(50, 40, 780, 40, fill="#f9e2af", width=4)
        c.create_text(70, 25, text="VDD", fill="#f9e2af", font=("Arial", 11, "bold"))

        c.create_line(50, self.rail_bottom, 780, self.rail_bottom, fill="#a6adc8", width=4)
        c.create_text(70, self.rail_bottom + 15, text="GND", fill="#a6adc8", font=("Arial", 11, "bold"))

        if gtype == 'INV':
            wp, wn = 2.0 * x_scale, 1.0 * x_scale
            self.draw_pmos(350, 150, wp, "Mp1")
            c.create_line(365, 40, 365, 135, fill="#f9e2af", width=2)
            self.draw_nmos(350, 410, wn, "Mn1")
            c.create_line(365, 425, 365, 520, fill="#a6adc8", width=2)
            c.create_line(365, 165, 365, 395, fill="#89b4fa", width=2)
            c.create_line(365, 280, 600, 280, fill="#89b4fa", width=3)
            c.create_text(620, 280, text="OUT", fill="#89b4fa", font=("Arial", 10, "bold"))
            c.create_line(200, 280, 315, 280, fill="#cdd6f4", width=2)
            c.create_line(315, 150, 315, 410, fill="#cdd6f4", width=2)
            c.create_line(315, 150, 325, 150, fill="#cdd6f4", width=2)
            c.create_text(180, 280, text="IN A", fill="#cdd6f4", font=("Arial", 10, "bold"))

        elif gtype in ('XOR', 'XNOR'):
            w_core_p, w_core_n = 4.0 * x_scale, 2.0 * x_scale
            c.create_rectangle(380, 80, 680, 480, outline="#a6e3a1", width=2, dash=(4, 4))
            c.create_text(530, 65, text=f"CORE {gtype} LOGIC BLOCK", fill="#a6e3a1", font=("Arial", 9, "bold"))

            if gtype == 'XOR':
                self.draw_pmos(450, 110, w_core_p, "PM3 (A)")
                self.draw_pmos(590, 110, w_core_p, "PM2 (B)")
                self.draw_pmos(450, 200, w_core_p, "PM0 (A_bar)")
                self.draw_pmos(590, 200, w_core_p, "PM1 (B_bar)")

                self.draw_nmos(450, 360, w_core_n, "NM4 (A_bar)")
                self.draw_nmos(450, 450, w_core_n, "NM2 (B_bar)")
                self.draw_nmos(590, 360, w_core_n, "NM5 (A)")
                self.draw_nmos(590, 450, w_core_n, "NM3 (B)")
            else:
                self.draw_pmos(450, 110, w_core_p, "PM1 (A)")
                self.draw_pmos(590, 110, w_core_p, "PM2 (B_bar)")
                self.draw_pmos(450, 200, w_core_p, "PM0 (A_bar)")
                self.draw_pmos(590, 200, w_core_p, "PM3 (B)")

                self.draw_nmos(450, 360, w_core_n, "NM4 (A_bar)")
                self.draw_nmos(450, 450, w_core_n, "NM2 (B)")
                self.draw_nmos(590, 360, w_core_n, "NM5 (A)")
                self.draw_nmos(590, 450, w_core_n, "NM3 (B_bar)")

            c.create_line(465, 40, 465, 95, fill="#f9e2af", width=2)
            c.create_line(605, 40, 605, 95, fill="#f9e2af", width=2)
            c.create_line(465, 125, 465, 185, fill="#f38ba8", width=2)
            c.create_line(605, 125, 605, 185, fill="#f38ba8", width=2)
            c.create_line(465, 155, 605, 155, fill="#f38ba8", width=2)

            c.create_line(465, 215, 465, 280, fill="#89b4fa", width=2)
            c.create_line(605, 215, 605, 280, fill="#89b4fa", width=2)
            c.create_line(465, 280, 605, 280, fill="#89b4fa", width=3)

            c.create_line(465, 375, 465, 435, fill="#89b4fa", width=2)
            c.create_line(605, 375, 605, 435, fill="#89b4fa", width=2)
            c.create_line(465, 465, 465, 520, fill="#a6adc8", width=2)
            c.create_line(605, 465, 605, 520, fill="#a6adc8", width=2)

            c.create_line(465, 280, 465, 345, fill="#89b4fa", width=2)
            c.create_line(605, 280, 605, 345, fill="#89b4fa", width=2)
            c.create_line(535, 280, 740, 280, fill="#89b4fa", width=3)
            c.create_text(755, 280, text="OUT", fill="#89b4fa", font=("Arial", 10, "bold"))

        elif gtype in ('NAND', 'NOR'):
            n_in = max(1, int(n_in))
            stack_x = 500
            stack_start_y = 80
            stack_step = 52
            output_x = 800

            def input_name(index):
                if index < 26:
                    return chr(ord('A') + index)
                return f"A{index - 25}"

            def draw_input(index, x, y):
                name = input_name(index)
                c.create_line(x - 110, y, x - 35, y, fill="#cdd6f4", width=2)
                c.create_text(x - 115, y, text=f"IN {name}", fill="#cdd6f4",
                              font=("Arial", 8, "bold"), anchor="e")

            if gtype == 'NAND':
                pmos_y = 120
                nmos_stack_start_y = 250
                nmos_stack_step = 50
                output_y = nmos_stack_start_y - 15
                pmos_xs = [
                    150 + index * 550 / max(n_in - 1, 1)
                    for index in range(n_in)
                ]
                for index, x in enumerate(pmos_xs):
                    self.draw_pmos(x, pmos_y, 2.0 * x_scale, f"Mp{index + 1}")
                    draw_input(index, x, pmos_y)
                    c.create_line(x + 15, 40, x + 15, pmos_y - 15,
                                  fill="#f9e2af", width=2)
                    c.create_line(x + 15, pmos_y + 15, x + 15, output_y,
                                  fill="#f38ba8", width=2)

                c.create_line(pmos_xs[0] + 15, output_y, output_x, output_y,
                              fill="#89b4fa", width=2)
                for index in range(n_in):
                    y = nmos_stack_start_y + index * nmos_stack_step
                    self.draw_nmos(stack_x, y, n_in * x_scale, f"Mn{index + 1}")
                    draw_input(index, stack_x, y)
                    if index < n_in - 1:
                        next_y = nmos_stack_start_y + (index + 1) * nmos_stack_step
                        c.create_line(stack_x + 15, y + 15, stack_x + 15, next_y - 15,
                                      fill="#89b4fa", width=2)
                    else:
                        c.create_line(stack_x + 15, y + 15, stack_x + 15, self.rail_bottom,
                                      fill="#a6adc8", width=2)

                c.create_line(stack_x + 15, nmos_stack_start_y - 15,
                              output_x, nmos_stack_start_y - 15, fill="#89b4fa", width=2)
                c.create_line(output_x, nmos_stack_start_y - 15, output_x, output_y,
                              fill="#89b4fa", width=2)
                c.create_text(output_x + 10, output_y, text="OUT", fill="#89b4fa",
                              font=("Arial", 10, "bold"), anchor="w")
            else:
                pmos_stack_start_y = 80
                pmos_stack_step = 62
                last_pmos_y = pmos_stack_start_y + (n_in - 1) * pmos_stack_step
                nmos_y = max(380, last_pmos_y + 110)
                output_y = nmos_y - 60
                ground_bus_y = nmos_y + 55
                nmos_xs = [
                    150 + index * 550 / max(n_in - 1, 1)
                    for index in range(n_in)
                ]
                for index, x in enumerate(nmos_xs):
                    self.draw_nmos(x, nmos_y, x_scale, f"Mn{index + 1}")
                    draw_input(index, x, nmos_y)
                    c.create_line(x + 15, nmos_y - 15, x + 15, output_y,
                                  fill="#89b4fa", width=2)
                    c.create_line(x + 15, nmos_y + 15, x + 15, ground_bus_y,
                                  fill="#a6adc8", width=2)

                c.create_line(nmos_xs[0] + 15, output_y, output_x, output_y,
                              fill="#89b4fa", width=2)
                c.create_line(nmos_xs[0] + 15, ground_bus_y, nmos_xs[-1] + 15, ground_bus_y,
                              fill="#a6adc8", width=2)
                c.create_line(nmos_xs[0] + 15, ground_bus_y, nmos_xs[0] + 15, self.rail_bottom,
                              fill="#a6adc8", width=2)

                for index in range(n_in):
                    y = pmos_stack_start_y + index * pmos_stack_step
                    self.draw_pmos(stack_x, y, 2.0 * n_in * x_scale, f"Mp{index + 1}")
                    draw_input(index, stack_x, y)
                    if index == 0:
                        c.create_line(stack_x + 15, 40, stack_x + 15, y - 15,
                                      fill="#f9e2af", width=2)
                    else:
                        previous_y = pmos_stack_start_y + (index - 1) * pmos_stack_step
                        c.create_line(stack_x + 15, previous_y + 15, stack_x + 15, y - 15,
                                      fill="#f38ba8", width=2)

                c.create_line(stack_x + 15, last_pmos_y + 15,
                              stack_x + 15, output_y, fill="#89b4fa", width=2)
                c.create_line(stack_x + 15, output_y, output_x, output_y,
                              fill="#89b4fa", width=2)
                c.create_text(output_x + 10, output_y, text="OUT", fill="#89b4fa",
                              font=("Arial", 10, "bold"), anchor="w")


# =====================================================================
# SCHEMATIC CANVAS WITH STAGE NUMBER DISPLAY
# =====================================================================
class SchematicCanvas(tk.Canvas):
    GRID_SIZE = 20

    def __init__(self, master, **kwargs):
        super().__init__(master, bg="#1e1e2e", highlightthickness=0, **kwargs)
        self.nodes = {}
        self.wires = []
        self.next_node_id = 1
        
        self.undo_stack = []

        self.highlight_path = True
        self.critical_full_path = []

        self.is_drawing_path = False
        self.building_path_nodes = []
        self.on_graphical_path_complete = None

        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.pan_start = None

        self.selected_node_id = None
        self.wiring_start_pin = None
        self.temp_wire_line = None
        self.on_node_selected = None

        self.bind("<ButtonPress-1>", self.on_click)
        self.bind("<Double-Button-1>", self.on_double_click)
        self.bind("<B1-Motion>", self.on_drag)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Motion>", self.on_mouse_move)

        self.bind("<ButtonPress-2>", self.start_pan)
        self.bind("<B2-Motion>", self.do_pan)
        self.bind("<ButtonPress-3>", self.start_pan)
        self.bind("<B3-Motion>", self.do_pan)

        self.bind("<MouseWheel>", self.on_zoom_wheel)
        self.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.1))
        self.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 0.9))

        self.draw_grid()

    def push_undo(self):
        state = {
            'nodes': copy.deepcopy(self.nodes),
            'wires': copy.deepcopy(self.wires),
            'next_node_id': self.next_node_id
        }
        self.undo_stack.append(state)
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def undo(self):
        if not self.undo_stack:
            return False
        state = self.undo_stack.pop()
        self.nodes = state['nodes']
        self.wires = state['wires']
        self.next_node_id = state['next_node_id']
        self.selected_node_id = None
        if callable(self.on_node_selected):
            self.on_node_selected(None)
        self.render()
        return True

    def to_screen(self, wx, wy):
        return (wx * self.zoom + self.pan_x, wy * self.zoom + self.pan_y)

    def to_world(self, sx, sy):
        return ((sx - self.pan_x) / self.zoom, (sy - self.pan_y) / self.zoom)

    def snap(self, val):
        return round(val / self.GRID_SIZE) * self.GRID_SIZE

    def start_pan(self, event):
        self.pan_start = (event.x, event.y)

    def do_pan(self, event):
        if self.pan_start:
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            self.pan_x += dx
            self.pan_y += dy
            self.pan_start = (event.x, event.y)
            self.render()

    def zoom_at(self, sx, sy, factor):
        new_zoom = max(0.3, min(3.0, self.zoom * factor))
        if new_zoom == self.zoom:
            return
        
        self.pan_x = sx - (sx - self.pan_x) * (new_zoom / self.zoom)
        self.pan_y = sy - (sy - self.pan_y) * (new_zoom / self.zoom)
        self.zoom = new_zoom
        self.render()

    def on_zoom_wheel(self, event):
        factor = 1.1 if event.delta > 0 else 0.9
        self.zoom_at(event.x, event.y, factor)

    def reset_view(self):
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.render()

    def draw_grid(self):
        self.delete("grid")
        g_size = self.GRID_SIZE * self.zoom
        if g_size < 8:
            return

        w, h = self.winfo_width() or 2000, self.winfo_height() or 2000
        start_x = self.pan_x % g_size
        start_y = self.pan_y % g_size

        x = start_x
        while x < w:
            self.create_line(x, 0, x, h, fill="#2a2a3c", tags="grid")
            x += g_size
        
        y = start_y
        while y < h:
            self.create_line(0, y, w, y, fill="#2a2a3c", tags="grid")
            y += g_size
        self.tag_lower("grid")

    def get_default_cin(self, gtype, inputs):
        if gtype == 'INV':
            return 3.0
        elif gtype == 'NAND':
            return float(inputs + 2)
        elif gtype == 'NOR':
            return float(2 * inputs + 1)
        elif gtype in ('XOR', 'XNOR'):
            return 6.0
        return 3.0

    def add_node(self, gtype, x=100, y=100, inputs=3, size=None, cl=120.0, name=None):
        self.push_undo()

        if gtype in ('XOR', 'XNOR'):
            inputs = 4
        elif gtype == 'INV':
            inputs = 1
        elif gtype in ('INPUT', 'OUTPUT'):
            inputs = 1 if gtype == 'OUTPUT' else 0
        else:
            inputs = max(2, inputs)

        if size is None:
            size = self.get_default_cin(gtype, inputs)

        if x == 100 and y == 100:
            wx, wy = self.to_world(400, 300)
            x, y = self.snap(wx), self.snap(wy)

        node_id = self.next_node_id
        self.next_node_id += 1

        if name is None:
            if gtype == 'INPUT':
                input_count = len([n for n in self.nodes.values() if n['type'] == 'INPUT'])
                name = chr(65 + input_count) if input_count < 26 else f"IN_{input_count+1}"
            elif gtype == 'OUTPUT':
                output_count = len([n for n in self.nodes.values() if n['type'] == 'OUTPUT'])
                name = "OUT" if output_count == 0 else f"OUT_{output_count+1}"
            else:
                type_count = len([n for n in self.nodes.values() if n['type'] == gtype]) + 1
                name = f"{gtype}{type_count}"

        self.nodes[node_id] = {
            'id': node_id,
            'name': name,
            'type': gtype,
            'x': self.snap(x),
            'y': self.snap(y),
            'inputs': inputs,
            'size': float(size),
            'cl': float(cl),
            'separate_inv': True
        }
        self.selected_node_id = node_id
        if callable(self.on_node_selected):
            self.on_node_selected(node_id)
        self.render()
        return node_id

    def get_pin_positions(self, node):
        x, y = node['x'], node['y']
        gtype = node['type']
        n_in = node['inputs']
        height = max(60, n_in * 20)

        in_pins = []
        if n_in == 1:
            in_pins.append((x - 40, y))
        else:
            spacing = height / (n_in + 1)
            for i in range(n_in):
                in_pins.append((x - 40, y - (height / 2) + spacing * (i + 1)))

        out_pins = []
        if gtype != 'OUTPUT':
            out_pins.append((x + 40, y))

        return in_pins, out_pins

    def get_pin_labels(self, node):
        gtype = node['type']
        n_in = node['inputs']
        if gtype in ('XOR', 'XNOR'):
            return ["A", "A_bar", "B", "B_bar"]
        elif gtype == 'INV':
            return ["A"]
        else:
            return [chr(65 + i) for i in range(n_in)]

    def find_pin_at(self, sx, sy, radius=12):
        wx, wy = self.to_world(sx, sy)
        for nid, node in self.nodes.items():
            in_pins, out_pins = self.get_pin_positions(node)
            for idx, (x, y) in enumerate(in_pins):
                spx, spy = self.to_screen(x, y)
                if math.hypot(sx - spx, sy - spy) <= radius:
                    return (nid, 'in', idx, x, y)
            for idx, (x, y) in enumerate(out_pins):
                spx, spy = self.to_screen(x, y)
                if math.hypot(sx - spx, sy - spy) <= radius:
                    return (nid, 'out', idx, x, y)
        return None

    def find_node_at(self, sx, sy):
        wx, wy = self.to_world(sx, sy)
        for nid, node in self.nodes.items():
            gtype = node['type']
            name = node.get('name', '')
            if gtype == 'OUTPUT':
                lbl_str = f"{name} ({node['cl']}C)"
                half_w = max(35, len(lbl_str) * 3.5 + 8)
            elif gtype == 'INPUT':
                half_w = max(20, len(name) * 4 + 6)
            else:
                half_w = 40

            if abs(wx - node['x']) <= half_w and abs(wy - node['y']) <= 30:
                return nid
        return None

    def on_click(self, event):
        if self.is_drawing_path:
            nid = self.find_node_at(event.x, event.y)
            if nid and nid in self.nodes:
                if not self.building_path_nodes or self.building_path_nodes[-1] != nid:
                    self.building_path_nodes.append(nid)
                    self.render()
                    if self.nodes[nid]['type'] == 'OUTPUT':
                        self.is_drawing_path = False
                        self.config(cursor="arrow")
                        if callable(self.on_graphical_path_complete):
                            self.on_graphical_path_complete(list(self.building_path_nodes))
            return

        pin = self.find_pin_at(event.x, event.y)
        if pin:
            if pin[1] == 'out':
                self.wiring_start_pin = pin
                return
            
        nid = self.find_node_at(event.x, event.y)
        if nid:
            self.push_undo()
        self.selected_node_id = nid
        if callable(self.on_node_selected):
            self.on_node_selected(nid)
        self.render()

    def on_double_click(self, event):
        if self.is_drawing_path:
            return
        nid = self.find_node_at(event.x, event.y)
        if nid and nid in self.nodes:
            node = self.nodes[nid]
            if node['type'] not in ('INPUT', 'OUTPUT'):
                stg = compute_stage_numbers(self.nodes, self.wires).get(nid, None)
                TransistorSchematicWindow(self.winfo_toplevel(), node, stage_num=stg)

    def on_drag(self, event):
        if self.is_drawing_path:
            return
        if self.wiring_start_pin:
            spx, spy = self.to_screen(self.wiring_start_pin[3], self.wiring_start_pin[4])
            if self.temp_wire_line:
                self.delete(self.temp_wire_line)
            self.temp_wire_line = self.create_line(spx, spy, event.x, event.y, fill="#89b4fa", width=2, dash=(4, 4))
        elif self.selected_node_id:
            node = self.nodes[self.selected_node_id]
            wx, wy = self.to_world(event.x, event.y)
            node['x'] = self.snap(wx)
            node['y'] = self.snap(wy)
            self.render()

    def on_release(self, event):
        if self.is_drawing_path:
            return
        if self.wiring_start_pin:
            if self.temp_wire_line:
                self.delete(self.temp_wire_line)
                self.temp_wire_line = None

            target_pin = self.find_pin_at(event.x, event.y)
            if target_pin and target_pin[1] == 'in' and target_pin[0] != self.wiring_start_pin[0]:
                self.push_undo()
                wire = {
                    'from_id': self.wiring_start_pin[0],
                    'to_id': target_pin[0],
                    'to_pin': target_pin[2]
                }
                self.wires = [w for w in self.wires if not (w['to_id'] == wire['to_id'] and w['to_pin'] == wire['to_pin'])]
                self.wires.append(wire)

            self.wiring_start_pin = None
            self.render()

    def on_mouse_move(self, event):
        if self.is_drawing_path:
            return
        pin = self.find_pin_at(event.x, event.y)
        self.config(cursor="hand2" if pin else "arrow")

    def route_wire_a_star(self, start_pos, end_pos, occupied_wire_cells):
        sx, sy = self.snap(start_pos[0]), self.snap(start_pos[1])
        ex, ey = self.snap(end_pos[0]), self.snap(end_pos[1])

        obstacles = set()
        padding = 10
        for nid, node in self.nodes.items():
            nx, ny = node['x'], node['y']
            h_h = max(25, node['inputs'] * 10)
            for ox in range(self.snap(nx - 35 - padding), self.snap(nx + 35 + padding) + 1, self.GRID_SIZE):
                for oy in range(self.snap(ny - h_h - padding), self.snap(ny + h_h + padding) + 1, self.GRID_SIZE):
                    obstacles.add((ox, oy))

        for dx in (-self.GRID_SIZE, 0, self.GRID_SIZE):
            for dy in (-self.GRID_SIZE, 0, self.GRID_SIZE):
                obstacles.discard((sx + dx, sy + dy))
                obstacles.discard((ex + dx, ey + dy))

        open_set = []
        heapq.heappush(open_set, (0, 0, sx, sy, None))
        came_from = {}
        g_score = {(sx, sy): 0}
        dirs = [(self.GRID_SIZE, 0), (-self.GRID_SIZE, 0), (0, self.GRID_SIZE), (0, -self.GRID_SIZE)]

        found = False
        target = (ex, ey)
        steps = 0

        while open_set and steps < 1200:
            steps += 1
            f, g, cx, cy, cur_dir = heapq.heappop(open_set)

            if (cx, cy) == target:
                found = True
                break

            for dx, dy in dirs:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in obstacles and (nx, ny) != target:
                    continue

                turn_cost = 8 if (cur_dir and cur_dir != (dx, dy)) else 0
                wire_penalty = 120 if (nx, ny) in occupied_wire_cells else 0

                new_g = g + self.GRID_SIZE + turn_cost + wire_penalty

                if (nx, ny) not in g_score or new_g < g_score[(nx, ny)]:
                    g_score[(nx, ny)] = new_g
                    h = abs(nx - ex) + abs(ny - ey)
                    heapq.heappush(open_set, (new_g + h, new_g, nx, ny, (dx, dy)))
                    came_from[(nx, ny)] = (cx, cy)

        if found:
            path = []
            curr = target
            while curr in came_from:
                path.append(curr)
                curr = came_from[curr]
            path.append((sx, sy))
            path.reverse()
            return simplify_path(path)
        else:
            mx = (sx + ex) / 2
            return simplify_path([(sx, sy), (mx, sy), (mx, ey), (ex, ey)])

    def render(self):
        self.delete("schematic")
        self.draw_grid()

        stage_map = compute_stage_numbers(self.nodes, self.wires)

        active_path = self.building_path_nodes if self.is_drawing_path else self.critical_full_path
        crit_nodes = set(active_path) if self.highlight_path or self.is_drawing_path else set()
        crit_wire_tuples = set(zip(active_path[:-1], active_path[1:])) if self.highlight_path or self.is_drawing_path else set()

        routed_world_paths = []
        occupied_wire_cells = set()

        for w_idx, wire in enumerate(self.wires):
            from_node = self.nodes.get(wire['from_id'])
            to_node = self.nodes.get(wire['to_id'])
            if from_node and to_node:
                _, out_pins = self.get_pin_positions(from_node)
                in_pins, _ = self.get_pin_positions(to_node)

                if out_pins and wire['to_pin'] < len(in_pins):
                    start_pos = out_pins[0]
                    end_pos = in_pins[wire['to_pin']]
                    
                    path = self.route_wire_a_star(start_pos, end_pos, occupied_wire_cells)
                    is_critical = (wire['from_id'], wire['to_id']) in crit_wire_tuples
                    routed_world_paths.append((w_idx, path, is_critical))

                    for pt in path:
                        occupied_wire_cells.add(pt)

        screen_h_segments = []
        screen_v_segments = []

        for w_idx, w_path, is_critical in routed_world_paths:
            s_path = [self.to_screen(px, py) for px, py in w_path]
            for i in range(len(s_path) - 1):
                p1, p2 = s_path[i], s_path[i+1]
                if abs(p1[1] - p2[1]) < 1:
                    screen_h_segments.append({'x1': p1[0], 'x2': p2[0], 'y': p1[1], 'wire_idx': w_idx, 'is_crit': is_critical})
                elif abs(p1[0] - p2[0]) < 1:
                    screen_v_segments.append({'x': p1[0], 'y1': p1[1], 'y2': p2[1], 'wire_idx': w_idx, 'is_crit': is_critical})

        def draw_horizontal_with_bridges(x1, x2, y, wire_idx, is_critical):
            start_x, end_x = min(x1, x2), max(x1, x2)
            if abs(start_x - end_x) < 2:
                return

            crossings = []
            for v in screen_v_segments:
                if v['wire_idx'] != wire_idx:
                    v_y1, v_y2 = min(v['y1'], v['y2']), max(v['y1'], v['y2'])
                    if start_x + 2 < v['x'] < end_x - 2 and v_y1 - 2 <= y <= v_y2 + 2:
                        crossings.append(v['x'])

            crossings.sort()
            r = max(4, min(10, int(6 * self.zoom)))
            curr_x = start_x

            color = "#f5c2e7" if (self.is_drawing_path and is_critical) else ("#ffd54f" if is_critical else "#89b4fa")
            w_stroke = max(3, int(4 * self.zoom)) if is_critical else max(2, int(3 * self.zoom))

            for cx in crossings:
                if cx - r > curr_x:
                    self.create_line(curr_x, y, cx - r, y, fill=color, width=w_stroke, tags="schematic")
                
                self.create_arc(cx - r, y - r, cx + r, y + r, start=0, extent=180, style=tk.ARC,
                                outline=color, width=w_stroke, tags="schematic")
                curr_x = cx + r

            if curr_x < end_x:
                self.create_line(curr_x, y, end_x, y, fill=color, width=w_stroke, tags="schematic")

        for v in screen_v_segments:
            color = "#f5c2e7" if (self.is_drawing_path and v['is_crit']) else ("#ffd54f" if v['is_crit'] else "#89b4fa")
            w_stroke = max(3, int(4 * self.zoom)) if v['is_crit'] else max(2, int(3 * self.zoom))
            self.create_line(v['x'], v['y1'], v['x'], v['y2'], fill=color, width=w_stroke, tags="schematic")

        for h in screen_h_segments:
            draw_horizontal_with_bridges(h['x1'], h['x2'], h['y'], h['wire_idx'], h['is_crit'])

        for nid, node in self.nodes.items():
            wx, wy = node['x'], node['y']
            x, y = self.to_screen(wx, wy)
            gtype = node['type']
            name = node.get('name', f"{gtype}{nid}")
            is_selected = (nid == self.selected_node_id)
            is_critical = nid in crit_nodes
            stg = stage_map.get(nid, None)

            if self.is_drawing_path and is_critical:
                outline_color = "#f5c2e7"
                wire_width = max(3, int(4 * self.zoom))
            elif is_selected and is_critical:
                outline_color = "#ff9800"
                wire_width = max(3, int(4 * self.zoom))
            elif is_selected:
                outline_color = "#f9e2af"
                wire_width = max(3, int(3 * self.zoom))
            elif is_critical:
                outline_color = "#ffd54f"
                wire_width = max(3, int(4 * self.zoom))
            else:
                outline_color = "#cba6f7"
                wire_width = max(2, int(2 * self.zoom))

            s30, s20, s15 = 30*self.zoom, 20*self.zoom, 15*self.zoom

            if gtype == 'INV':
                self.create_polygon(x-s20, y-s20, x-s20, y+s20, x+s15, y, 
                                    fill="#313244", outline=outline_color, width=wire_width, tags="schematic")
                self.create_oval(x+s15, y-4*self.zoom, x+s15+8*self.zoom, y+4*self.zoom, fill="#313244", outline=outline_color, width=wire_width, tags="schematic")
            elif gtype == 'NAND':
                height = max(50*self.zoom, node['inputs'] * 15 * self.zoom)
                self.create_rectangle(x-s30, y-height/2, x, y+height/2, fill="#313244", outline=outline_color, width=wire_width, tags="schematic")
                self.create_arc(x-25*self.zoom, y-height/2, x+20*self.zoom, y+height/2, start=-90, extent=180, fill="#313244", outline=outline_color, width=wire_width, tags="schematic")
                self.create_oval(x+20*self.zoom, y-4*self.zoom, x+28*self.zoom, y+4*self.zoom, fill="#313244", outline=outline_color, width=wire_width, tags="schematic")
            elif gtype == 'NOR':
                height = max(50*self.zoom, node['inputs'] * 15 * self.zoom)
                top_y = y - height / 2
                bot_y = y + height / 2
                self.create_polygon(
                    x-s30, top_y,
                    x-s15, y,
                    x-s30, bot_y,
                    x-5*self.zoom, bot_y,
                    x+18*self.zoom, y,
                    x-5*self.zoom, top_y,
                    fill="#313244", outline=outline_color, width=wire_width, smooth=True, tags="schematic"
                )
                self.create_oval(x+18*self.zoom, y-4*self.zoom, x+26*self.zoom, y+4*self.zoom, fill="#313244", outline=outline_color, width=wire_width, tags="schematic")
            elif gtype in ('XOR', 'XNOR'):
                height = max(50*self.zoom, node['inputs'] * 15 * self.zoom)
                top_y = y - height / 2
                bot_y = y + height / 2
                self.create_arc(x-42*self.zoom, top_y, x-26*self.zoom, bot_y, start=-90, extent=180, style=tk.ARC, outline=outline_color, width=wire_width, tags="schematic")
                self.create_polygon(
                    x-s30, top_y,
                    x-s15, y,
                    x-s30, bot_y,
                    x-5*self.zoom, bot_y,
                    x+18*self.zoom, y,
                    x-5*self.zoom, top_y,
                    fill="#313244", outline=outline_color, width=wire_width, smooth=True, tags="schematic"
                )
                if gtype == 'XNOR':
                    self.create_oval(x+18*self.zoom, y-4*self.zoom, x+26*self.zoom, y+4*self.zoom, fill="#313244", outline=outline_color, width=wire_width, tags="schematic")
            elif gtype == 'INPUT':
                box_w = max(40 * self.zoom, (len(name) * 8 + 12) * self.zoom)
                self.create_rectangle(x - box_w/2, y - s15, x + box_w/2, y + s15, fill="#a6e3a1", outline=outline_color, width=wire_width, tags="schematic")
                self.create_text(x, y, text=name, fill="#11111b", font=("Arial", max(7, int(9 * self.zoom)), "bold"), tags="schematic")
            elif gtype == 'OUTPUT':
                lbl_str = f"{name} ({node['cl']}C)"
                box_w = max(70 * self.zoom, (len(lbl_str) * 7 + 16) * self.zoom)
                self.create_rectangle(x - box_w/2, y - s15, x + box_w/2, y + s15, fill="#f38ba8", outline=outline_color, width=wire_width, tags="schematic")
                self.create_text(x, y, text=lbl_str, fill="#11111b", font=("Arial", max(7, int(8 * self.zoom)), "bold"), tags="schematic")

            if gtype not in ('INPUT', 'OUTPUT'):
                lbl = f"[Stage {stg}] {name} (Cin={node['size']:.1f}C)"
                self.create_text(x, y - max(30*self.zoom, node['inputs']*10*self.zoom), text=lbl, fill="#cdd6f4", font=("Arial", max(7, int(9 * self.zoom))), tags="schematic")

            in_pins, out_pins = self.get_pin_positions(node)
            pin_labels = self.get_pin_labels(node)

            for idx, (px, py) in enumerate(in_pins):
                spx, spy = self.to_screen(px, py)
                self.create_oval(spx-4*self.zoom, spy-4*self.zoom, spx+4*self.zoom, spy+4*self.zoom, fill="#f38ba8", outline="#ffffff", tags="schematic")
                
                if idx < len(pin_labels) and gtype not in ('INPUT', 'OUTPUT'):
                    lbl_text = pin_labels[idx]
                    self.create_text(spx - 8 * self.zoom, spy, text=lbl_text, fill="#f5c2e7", 
                                     font=("Arial", max(6, int(8 * self.zoom)), "bold"), anchor="e", tags="schematic")

            for px, py in out_pins:
                spx, spy = self.to_screen(px, py)
                self.create_oval(spx-4*self.zoom, spy-4*self.zoom, spx+4*self.zoom, spy+4*self.zoom, fill="#a6e3a1", outline="#ffffff", tags="schematic")

        if self.is_drawing_path:
            p_names = []
            for nid in self.building_path_nodes:
                n = self.nodes[nid]
                if n['type'] == 'INPUT':
                    p_names.append(n.get('name', str(nid)))
                elif n['type'] == 'OUTPUT':
                    p_names.append(f"{n.get('name', str(nid))} ({n['cl']}C)")
                else:
                    p_names.append(f"{n.get('name', str(nid))}[S{stage_map.get(nid, '?')}]")
            path_str = " -> ".join(p_names) if p_names else "None"
            msg = f"🎯 GRAPHICAL PATH MODE: Click gates in order (Start Input -> Logic Gates -> Output Pin)\nSelected: {path_str}"
            self.create_rectangle(10, 10, self.winfo_width()-10 if self.winfo_width() > 100 else 600, 50, fill="#f5c2e7", outline="#11111b", tags="schematic")
            self.create_text(20, 30, text=msg, fill="#11111b", font=("Arial", 10, "bold"), anchor="w", tags="schematic")


# =====================================================================
# MAIN WORKBENCH GUI APP
# =====================================================================
class VLSIWorkbenchApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VLSI Logical Effort & Stick Diagram Workbench")
        self.geometry("1340x820")
        self.configure(bg="#181825")

        self.custom_graphical_path = None

        self.bind_all("<Delete>", lambda e: self.delete_selected_node())
        self.bind_all("<BackSpace>", lambda e: self.delete_selected_node())
        self.bind_all("<Control-z>", lambda e: self.canvas.undo())
        self.bind_all("<Command-z>", lambda e: self.canvas.undo())

        self.setup_ui()

    def setup_ui(self):
        toolbar = ttk.Frame(self, padding=5)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        row1 = ttk.Frame(toolbar)
        row1.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        ttk.Button(row1, text="↩️ Undo", command=lambda: self.canvas.undo()).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        ttk.Label(row1, text="Add Gate:").pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="+ INV", command=lambda: self.add_gate('INV')).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(row1, text="Inputs (N):").pack(side=tk.LEFT, padx=(6, 2))
        self.inputs_spin = ttk.Spinbox(row1, from_=2, to=8, width=3)
        self.inputs_spin.set(2)
        self.inputs_spin.pack(side=tk.LEFT, padx=2)

        ttk.Button(row1, text="+ NAND", command=lambda: self.add_gate('NAND')).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="+ NOR", command=lambda: self.add_gate('NOR')).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="+ XOR", command=lambda: self.add_gate('XOR')).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="+ XNOR", command=lambda: self.add_gate('XNOR')).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="+ Input Pin", command=lambda: self.add_gate('INPUT')).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="+ Output/CL", command=lambda: self.add_gate('OUTPUT')).pack(side=tk.LEFT, padx=2)

        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(row1, text="🗑️ Delete", command=self.delete_selected_node).pack(side=tk.LEFT, padx=2)

        row2 = ttk.Frame(toolbar)
        row2.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        ttk.Label(row2, text="Zoom:").pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="🔍+", command=lambda: self.canvas.zoom_at(400, 300, 1.2)).pack(side=tk.LEFT, padx=1)
        ttk.Button(row2, text="🔍-", command=lambda: self.canvas.zoom_at(400, 300, 0.8)).pack(side=tk.LEFT, padx=1)
        ttk.Button(row2, text="🎯 100%", command=lambda: self.canvas.reset_view()).pack(side=tk.LEFT, padx=2)

        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        ttk.Button(row2, text="Export JSON", command=self.export_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="Import JSON", command=self.import_json).pack(side=tk.LEFT, padx=2)

        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        self.highlight_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="✨ Highlight Path", variable=self.highlight_var, command=self.toggle_path_highlight).pack(side=tk.LEFT, padx=3)

        ttk.Button(row2, text="🎯 Draw Path", command=self.start_draw_path_mode).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="🔄 Auto Path", command=self.reset_to_auto_path).pack(side=tk.LEFT, padx=2)

        row3 = ttk.Frame(toolbar)
        row3.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(row3, text="Path Selection:").pack(side=tk.LEFT, padx=(3, 2))
        self.path_combo = ttk.Combobox(row3, state="readonly", width=55)
        self.path_combo.pack(side=tk.LEFT, padx=2)
        self.path_combo.bind("<<ComboboxSelected>>", lambda e: self.on_path_combo_selected())

        ttk.Button(row3, text="⚡ Calculate & Size Effort", command=self.run_calc).pack(side=tk.RIGHT, padx=5)
        ttk.Button(row3, text="📊 Truth Table", command=self.show_truth_table_popup).pack(side=tk.RIGHT, padx=2)

        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        self.canvas = SchematicCanvas(main_pane)
        self.canvas.on_node_selected = self.on_node_selected
        self.canvas.on_graphical_path_complete = self.on_graphical_path_complete
        main_pane.add(self.canvas, weight=3)

        sidebar = ttk.Frame(main_pane, padding=10)
        main_pane.add(sidebar, weight=1)

        ttk.Label(sidebar, text="Property Inspector", font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=5)
        
        self.prop_frame = ttk.Frame(sidebar)
        self.prop_frame.pack(fill=tk.X, pady=5)

        ttk.Separator(sidebar, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        ttk.Label(sidebar, text="Calculation Output Summary", font=("Arial", 11, "bold")).pack(anchor=tk.W, pady=(0, 5))

        summary_card = ttk.Frame(sidebar, padding=8, relief=tk.RIDGE)
        summary_card.pack(fill=tk.X, pady=2)

        ttk.Label(summary_card, text="Ideal Delay (Pre-sizing):", font=("Arial", 9, "bold")).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.lbl_ideal_d = ttk.Label(summary_card, text="-- τ", font=("Arial", 10, "bold"), foreground="#89b4fa")
        self.lbl_ideal_d.grid(row=0, column=1, sticky=tk.E, padx=(10, 0))

        ttk.Label(summary_card, text="Actual Delay (Post-sizing):", font=("Arial", 9, "bold")).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.lbl_actual_d = ttk.Label(summary_card, text="-- τ", font=("Arial", 10, "bold"), foreground="#a6e3a1")
        self.lbl_actual_d.grid(row=1, column=1, sticky=tk.E, padx=(10, 0))

        ttk.Label(summary_card, text="Calculated N_opt:", font=("Arial", 9, "bold")).grid(row=2, column=0, sticky=tk.W, pady=2)
        self.lbl_n_opt = ttk.Label(summary_card, text="-- stages", font=("Arial", 10, "bold"), foreground="#fab387")
        self.lbl_n_opt.grid(row=2, column=1, sticky=tk.E, padx=(10, 0))

        summary_card.columnconfigure(0, weight=1)

        self.show_details_var = tk.BooleanVar(value=False)
        self.btn_toggle_details = ttk.Button(sidebar, text="▼ Show Detailed Calculations", command=self.toggle_details_panel)
        self.btn_toggle_details.pack(fill=tk.X, pady=(10, 5))

        self.details_frame = ttk.Frame(sidebar)
        self.output_text = tk.Text(self.details_frame, bg="#11111b", fg="#a6e3a1", insertbackground="white", font=("Consolas", 8), height=15)
        self.output_text.pack(fill=tk.BOTH, expand=True)

    def start_draw_path_mode(self):
        self.canvas.is_drawing_path = True
        self.canvas.building_path_nodes = []
        self.canvas.config(cursor="crosshair")
        self.canvas.render()

    def reset_to_auto_path(self):
        self.custom_graphical_path = None
        self.canvas.is_drawing_path = False
        self.canvas.building_path_nodes = []
        self.canvas.config(cursor="arrow")
        if self.path_combo['values']:
            self.path_combo.current(0)
        self.run_calc()

    def on_graphical_path_complete(self, path_sequence):
        if len(path_sequence) < 2:
            messagebox.showwarning("Path Error", "Path must contain at least 2 connected nodes.")
            self.reset_to_auto_path()
            return

        out_edges = {n: [] for n in self.canvas.nodes}
        for w in self.canvas.wires:
            out_edges[w['from_id']].append(w['to_id'])

        for i in range(len(path_sequence) - 1):
            if path_sequence[i+1] not in out_edges.get(path_sequence[i], []):
                g1_name = self.canvas.nodes[path_sequence[i]].get('name', f"Gate #{path_sequence[i]}")
                g2_name = self.canvas.nodes[path_sequence[i+1]].get('name', f"Gate #{path_sequence[i+1]}")
                messagebox.showerror("Invalid Path Connection", f"{g1_name} and {g2_name} are not directly connected by a wire!")
                self.reset_to_auto_path()
                return

        self.custom_graphical_path = path_sequence
        self.run_calc()

    def on_path_combo_selected(self):
        sel_str = self.path_combo.get()
        if "[Graphical Custom]" not in sel_str:
            self.custom_graphical_path = None
        self.run_calc()

    def toggle_path_highlight(self):
        self.canvas.highlight_path = self.highlight_var.get()
        self.canvas.render()

    def toggle_details_panel(self):
        if self.show_details_var.get():
            self.show_details_var.set(False)
            self.details_frame.pack_forget()
            self.btn_toggle_details.config(text="▼ Show Detailed Calculations")
        else:
            self.show_details_var.set(True)
            self.details_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            self.btn_toggle_details.config(text="▲ Hide Detailed Calculations")

    def add_gate(self, gtype):
        n_in = int(self.inputs_spin.get()) if gtype in ('NAND', 'NOR') else (4 if gtype in ('XOR', 'XNOR') else 1)
        self.canvas.add_node(gtype, x=100, y=100, inputs=n_in)

    def show_truth_table_popup(self):
        graph_data = self.get_graph_export()
        tt_str = generate_truth_table(graph_data)

        win = tk.Toplevel(self)
        win.title("Circuit Truth Table")
        win.geometry("500x420")
        win.configure(bg="#11111b")

        ttk.Label(win, text="Circuit Logic Output Truth Table", font=("Arial", 11, "bold")).pack(pady=10)
        txt = tk.Text(win, bg="#1e1e2e", fg="#a6e3a1", font=("Consolas", 10), wrap=tk.NONE)
        txt.insert(tk.END, tt_str)
        txt.config(state=tk.DISABLED)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def on_node_selected(self, node_id):
        for widget in self.prop_frame.winfo_children():
            widget.destroy()

        if not node_id or node_id not in self.canvas.nodes:
            ttk.Label(self.prop_frame, text="No gate selected.\nClick a gate to edit properties.\nDouble-click for transistor view.", foreground="#888888").pack(anchor=tk.W)
            return

        node = self.canvas.nodes[node_id]
        stage_map = compute_stage_numbers(self.canvas.nodes, self.canvas.wires)
        stg = stage_map.get(node_id, None)

        if node['type'] not in ('INPUT', 'OUTPUT'):
            ttk.Label(self.prop_frame, text=f"Topological Stage: Stage {stg}", font=("Arial", 9, "bold"), foreground="#ffd54f").pack(anchor=tk.W, pady=(0, 6))
        elif node['type'] == 'INPUT':
            ttk.Label(self.prop_frame, text="Primary Input Pin", font=("Arial", 9, "bold"), foreground="#a6e3a1").pack(anchor=tk.W, pady=(0, 6))
        else:
            ttk.Label(self.prop_frame, text="Primary Output Load Pin", font=("Arial", 9, "bold"), foreground="#f38ba8").pack(anchor=tk.W, pady=(0, 6))

        ttk.Label(self.prop_frame, text="Label / Name:").pack(anchor=tk.W, pady=(0, 2))
        name_var = tk.StringVar(value=node.get('name', f"{node['type']}{node['id']}"))
        
        def on_name_change(*args):
            new_val = name_var.get()
            if node.get('name') != new_val:
                node['name'] = new_val
                self.canvas.render()

        name_var.trace_add("write", on_name_change)

        name_entry = ttk.Entry(self.prop_frame, textvariable=name_var)
        name_entry.pack(fill=tk.X, pady=(0, 8))
        name_entry.bind("<FocusIn>", lambda e: self.canvas.push_undo())
        name_entry.bind("<Return>", lambda e: self.focus())

        if node['type'] not in ('INPUT', 'OUTPUT'):
            if node['type'] in ('NAND', 'NOR'):
                ttk.Label(self.prop_frame, text="Number of Inputs (N):").pack(anchor=tk.W, pady=(4, 0))
                nin_var = tk.IntVar(value=node['inputs'])

                def update_nin(*args):
                    try:
                        val = nin_var.get()
                        if val != node['inputs'] and 2 <= val <= 8:
                            self.canvas.push_undo()
                            node['inputs'] = val
                            self.canvas.wires = [w for w in self.canvas.wires if not (w['to_id'] == node['id'] and w['to_pin'] >= val)]
                            self.canvas.render()
                    except tk.TclError:
                        pass

                nin_spin = ttk.Spinbox(self.prop_frame, from_=2, to=8, textvariable=nin_var)
                nin_spin.pack(fill=tk.X, pady=(0, 6))
                nin_spin.bind("<FocusIn>", lambda e: self.canvas.push_undo())
                nin_spin.bind("<Return>", lambda e: update_nin())

            ttk.Label(self.prop_frame, text="Input Cap S (in terms of C):").pack(anchor=tk.W, pady=(5, 0))
            size_var = tk.DoubleVar(value=node['size'])
            
            def on_size_change(*args):
                try:
                    val = size_var.get()
                    if node.get('size') != val:
                        node['size'] = float(val)
                        self.canvas.render()
                except tk.TclError:
                    pass
                    
            size_var.trace_add("write", on_size_change)
            size_spin = ttk.Spinbox(self.prop_frame, from_=0.1, to=1000.0, increment=1.0, textvariable=size_var)
            size_spin.pack(fill=tk.X)
            input_driven = any(
                wire['to_id'] == node['id']
                and self.canvas.nodes.get(wire['from_id'], {}).get('type') == 'INPUT'
                for wire in self.canvas.wires
            )
            if input_driven:
                size_spin.configure(state=tk.DISABLED)
            size_spin.bind("<FocusIn>", lambda e: self.canvas.push_undo())
            size_spin.bind("<Return>", lambda e: self.focus())

            if node['type'] in ('XOR', 'XNOR'):
                ttk.Label(
                    self.prop_frame, 
                    text="🔀 Separated Inverters Model\n   (Inputs: A, A_bar, B, B_bar)", 
                    font=("Arial", 8, "italic"),
                    foreground="#fab387"
                ).pack(anchor=tk.W, pady=4)

            ttk.Button(self.prop_frame, text="🔍 Transistor View", 
                       command=lambda: TransistorSchematicWindow(self, node, stage_num=stg)).pack(fill=tk.X, pady=4)

        if node['type'] == 'OUTPUT':
            ttk.Label(self.prop_frame, text="Load Cap CL (in terms of C):").pack(anchor=tk.W, pady=(5, 0))
            cl_var = tk.DoubleVar(value=node['cl'])

            def on_cl_change(*args):
                try:
                    val = cl_var.get()
                    if node.get('cl') != val:
                        node['cl'] = float(val)
                        self.canvas.render()
                except tk.TclError:
                    pass

            cl_var.trace_add("write", on_cl_change)
            cl_spin = ttk.Spinbox(self.prop_frame, from_=1.0, to=5000.0, increment=5.0, textvariable=cl_var)
            cl_spin.pack(fill=tk.X)
            cl_spin.bind("<FocusIn>", lambda e: self.canvas.push_undo())
            cl_spin.bind("<Return>", lambda e: self.focus())

        ttk.Button(self.prop_frame, text="🗑️ Delete Gate", command=self.delete_selected_node).pack(anchor=tk.W, pady=12)

    def delete_selected_node(self):
        nid = self.canvas.selected_node_id
        if nid and nid in self.canvas.nodes:
            self.canvas.push_undo()
            del self.canvas.nodes[nid]
            self.canvas.wires = [w for w in self.canvas.wires if w['from_id'] != nid and w['to_id'] != nid]
            self.canvas.selected_node_id = None
            self.on_node_selected(None)
            self.canvas.render()

    def get_graph_export(self):
        return {
            "nodes": list(self.canvas.nodes.values()),
            "wires": self.canvas.wires
        }

    def export_json(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if file_path:
            with open(file_path, "w") as f:
                json.dump(self.get_graph_export(), f, indent=2)
            messagebox.showinfo("Export Success", "Schematic exported successfully!")

    def import_json(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if file_path:
            self.canvas.push_undo()
            with open(file_path, "r") as f:
                data = json.load(f)

            self.canvas.nodes = {n['id']: n for n in data.get("nodes", [])}
            for node in self.canvas.nodes.values():
                node.pop('locked', None)
            self.canvas.wires = data.get("wires", [])
            max_id = max([n['id'] for n in self.canvas.nodes.values()], default=0)
            self.canvas.next_node_id = max_id + 1
            self.canvas.selected_node_id = None
            self.custom_graphical_path = None
            self.on_node_selected(None)
            self.canvas.render()
            messagebox.showinfo("Import Success", "Schematic loaded successfully!")

    def run_calc(self):
        graph_data = self.get_graph_export()
        
        raw_idx = self.path_combo.current()
        if raw_idx < 0:
            raw_idx = 0

        if self.custom_graphical_path:
            manual_idx = 0
        else:
            manual_idx = raw_idx

        summary, output_text, cin_dict, path_options = calculate_logical_effort(
            graph_data, manual_path_index=manual_idx, custom_graphical_path=self.custom_graphical_path
        )

        self.path_combo['values'] = path_options

        if self.custom_graphical_path:
            self.path_combo.current(1)
        elif raw_idx < len(path_options):
            self.path_combo.current(raw_idx)
        else:
            self.path_combo.current(0)

        self.lbl_ideal_d.config(text=f"{summary.get('pre_sizing_D', 0.0):.3f} τ")
        self.lbl_actual_d.config(text=f"{summary.get('actual_D', 0.0):.3f} τ")
        self.lbl_n_opt.config(text=f"{summary.get('N_opt_int', 0)} stages ({summary.get('N_opt', 0.0):.2f})")

        self.canvas.critical_full_path = summary.get("critical_full_path", [])

        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, output_text)

        if isinstance(cin_dict, dict):
            self.canvas.push_undo()
            for nid, new_cin in cin_dict.items():
                if nid in self.canvas.nodes:
                    node = self.canvas.nodes[nid]
                    node['size'] = float(round(new_cin, 1))

            self.canvas.render()
            if self.canvas.selected_node_id:
                self.on_node_selected(self.canvas.selected_node_id)


if __name__ == "__main__":
    app = VLSIWorkbenchApp()
    app.mainloop()