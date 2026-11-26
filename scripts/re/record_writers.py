"""Find the D3D12.X inline command-list record writers in XboxBvhBuilder.dll (objdump AT&T
listing): `mov 0x18(%L),%P ; cmp 0x30|0x28(%L),%P ; jae fallback` … `add $N,%P ; mov %P,0x18(%L)`.
Per site: list register, bound field, record length, header (immediate or list field) and
the vtable slot of the fallback call. Branch targets may have or omit the 0x prefix.

usage: objdump -d --no-show-raw-insn XboxBvhBuilder.dll > bvhb.asm; python record_writers.py bvhb.asm"""
import re, collections, sys

REG_FAMILIES = (
    {'rax', 'eax', 'ax', 'al', 'ah'},
    {'rbx', 'ebx', 'bx', 'bl', 'bh'},
    {'rcx', 'ecx', 'cx', 'cl', 'ch'},
    {'rdx', 'edx', 'dx', 'dl', 'dh'},
    {'rsi', 'esi', 'si', 'sil'},
    {'rdi', 'edi', 'di', 'dil'},
    {'rbp', 'ebp', 'bp', 'bpl'},
    {'rsp', 'esp', 'sp', 'spl'},
    *({f'r{n}', f'r{n}d', f'r{n}w', f'r{n}b'} for n in range(8, 16)),
)
PREFIXES = {'lock', 'rep', 'repe', 'repz', 'repne', 'repnz'}


def _reg_aliases(reg):
    for fam in REG_FAMILIES:
        if reg in fam:
            return fam
    return {reg}


def _split_operands(text):
    ops, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif ch == ',' and depth == 0:
            ops.append(text[start:i].strip())
            start = i + 1
    if text[start:].strip():
        ops.append(text[start:].strip())
    return ops


def _writes_reg(insn, reg):
    tokens = insn.split(None, 1)
    while tokens and tokens[0] in PREFIXES:
        tokens = tokens[1].split(None, 1) if len(tokens) > 1 else []
    if not tokens:
        return False
    mn = tokens[0]
    aliases = _reg_aliases(reg)
    if mn.startswith('call'):
        return True
    if mn.startswith('cmpxchg'):
        # Failure loads the accumulator, or the high:low pair for a double-width compare.
        if 'rax' in aliases or (mn in ('cmpxchg8b', 'cmpxchg16b') and 'rdx' in aliases):
            return True
    elif mn.startswith(('cmp', 'test', 'j', 'nop', 'prefetch')) or mn in ('bt', 'ret', 'retq'):
        return False
    ops = _split_operands(tokens[1]) if len(tokens) > 1 else []
    if (mn.startswith(('mul', 'div', 'idiv', 'cqto', 'cdq')) or (mn.startswith('imul') and len(ops) == 1)) and (aliases & {'rax', 'rdx'}):
        return True
    if not ops:
        return False
    targets = ops if mn.startswith(('xchg', 'xadd')) else [ops[-1]]
    return any(op.startswith('%') and op[1:] in aliases for op in targets)

lines = open(sys.argv[1], encoding='utf-8', errors='replace').read().splitlines()
ins = []
for l in lines:
    m = re.match(r'\s+([0-9a-f]+):\s+(.*)$', l)
    if m:
        ins.append((int(m.group(1), 16), m.group(2).strip()))
idx = {a: i for i, (a, _) in enumerate(ins)}
sites = []
for i, (a, t) in enumerate(ins):
    m = re.match(r'mov\s+0x18\(%(\w+)\),%(\w+)$', t)
    if not m:
        continue
    L, P = m.groups()
    if i + 2 >= len(ins):
        continue
    m2 = re.match(rf'cmp\s+0x(30|28)\(%{L}\),%{P}$', ins[i + 1][1])
    m3 = re.match(r'jae\s+(?:0x)?([0-9a-f]+)', ins[i + 2][1])
    if not (m2 and m3):
        continue
    bound, fallback = m2.group(1), int(m3.group(1), 16)
    body = []
    length = None
    cursor_store = rf'mov\s+%(\w+),0x18\(%{L}\)$'
    cursor_updated = False
    for j in range(i + 3, min(i + 60, len(ins))):
        address, tj = ins[j]
        if a < fallback <= address or re.match(r'retq?\b', tj):
            break
        body.append(tj)
        ma = re.match(rf'add\s+\$0x([0-9a-f]+),%{P}$', tj)
        if ma:
            length = int(ma.group(1), 16)
        store = re.match(cursor_store, tj)
        if store:
            cursor_updated = True
            if length is None:
                dst = store.group(1)
                # lea 0xN(%P),%dst style: trust only when %P is untouched beforehand and %dst survives to the store
                p_clean = True
                lea_len = None
                for tb in body[:-1]:
                    ml = re.match(rf'lea\s+0x([0-9a-f]+)\(%{P}\),%{dst}$', tb)
                    if ml:
                        lea_len = int(ml.group(1), 16) if p_clean else None
                        if _reg_aliases(dst) == _reg_aliases(P):
                            p_clean = False
                    else:
                        if _writes_reg(tb, dst):
                            lea_len = None
                        if _writes_reg(tb, P):
                            p_clean = False
                length = lea_len
            break
    if not cursor_updated:
        continue
    # Read the first move into the record header, accepting either spelling of offset zero.
    header = '?'
    for k, tb in enumerate(body):
        store = re.fullmatch(rf'movl?\s+(?:\$0x([0-9a-f]+)|(%\w+)),(?:0x0)?\(%{P}\)', tb)
        if not store:
            continue
        immediate, register = store.groups()
        if immediate is not None:
            header = 'imm ' + immediate
        elif k > 0:
            # An adjacent load into the stored register proves a direct list-field copy.
            load = re.fullmatch(rf'movl?\s+0x([0-9a-f]+)\(%{L}\),{register}', body[k - 1])
            if load:
                header = 'list+' + load.group(1)
        break
    # fallback: first indirect call at/after the jae target
    slot = '?'
    k = idx.get(fallback)
    if k is not None:
        for j in range(k, min(k + 12, len(ins))):
            mc = re.match(r'call\s+\*0x([0-9a-f]+)\(%\w+\)$', ins[j][1])
            if mc:
                slot = int(mc.group(1), 16) // 8
                break
    sites.append((a, L, bound, length, header, slot))

print(f'{len(sites)} record write sites')
kinds = collections.Counter((h, ln, s, b) for _, _, b, ln, h, s in sites)
for (h, ln, s, b), n in kinds.most_common():
    print(f'  {n:3}× header {h:18} length {ln} B  bound +0x{b}  fallback slot {s}')
