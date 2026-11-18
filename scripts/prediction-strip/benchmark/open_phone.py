"""Saved key presses at the open phone's counts of shown words (4 to 7), dev and test halves."""
import json
import numpy as np
R = "scripts/prediction-strip/benchmark/results"
dev = json.load(open(f'{R}/dev.json')); test = json.load(open(f'{R}/test.json'))
W = dev['strip_words']; OPEN = [W.index(n) for n in (4, 5, 6, 7)]; CLOSED = [W.index(n) for n in (3, 4, 5)]
def val(d, name, n): return 100 * d['orders'][name]['saved'][f'{n}/1']['mean'][0]
CH = 'shipped|typed|engine|0.3'
print('per count, typist 1:  ' + '  '.join(f'N={n}' for n in W))
for half, d in (('dev', dev), ('test', test)):
    for name in ('E', CH):
        print(f'{half:5} {name:28}', '  '.join(f'{val(d, name, n):5.1f}' for n in W),
              ' open 4-7: %.1f  closed 3-5: %.1f' % (np.mean([val(d, name, n) for n in (4,5,6,7)]), np.mean([val(d, name, n) for n in (3,4,5)])))
for half in ('dev', 'test'):
    z = np.load(f'build/prediction-strip/bench/results/{half}.npz', allow_pickle=True)
    print(half, 'npz keys', list(z.keys()))
    names = [str(n) for n in z['names']] if 'names' in z else list((dev if half == 'dev' else test)['orders'])
    s = z['samples'].astype(np.float64); v = z['values'].astype(np.float64) if 'values' in z else None
    def openmean(i): return s[:, i][:, OPEN, 0].mean(axis=(0, 1))      # over sets and counts -> samples
    c = names.index(CH); base = openmean(c)
    d = dev if half == 'dev' else test
    point = lambda n: np.mean([val(d, n, k) for k in (4, 5, 6, 7)])
    rows = []
    for i, n in enumerate(names):
        diff = 100 * (openmean(i) - base)
        rows.append((point(n) - point(CH), np.percentile(diff, 2.5), np.percentile(diff, 97.5), n, point(n)))
    rows.sort(reverse=True)
    print(f'{half}: difference to the choice at 4-7 words, points (95% paired interval)')
    show = rows[:12] if half == 'dev' else rows
    for r in show: print('  %+6.2f (%+6.2f to %+6.2f)  %5.1f  %s' % (r[0], r[1], r[2], r[4], r[3]))
    if half == 'dev':
        for r in rows:
            if r[3] in ('E', 'shipped|typed_built|none|0.3', 'shipped|model|none|0.0', 'shipped|typed|engine|0.2', 'shipped|typed|engine|0.5', 'shipped|typed|engine|0.0') or r[3].endswith('|R'):
                print('  %+6.2f (%+6.2f to %+6.2f)  %5.1f  %s' % (r[0], r[1], r[2], r[4], r[3]))
