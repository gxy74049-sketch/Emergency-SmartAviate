"""Preset data loader. Does not execute simulation or scheduling."""
from pathlib import Path
import argparse
import copy
import json
import math
import random

ROOT = Path(__file__).resolve().parent
ROUTES = {'A':['W','A'],'B':['W','A','B'],'C':['W','C'],
          'D':['W','A','X','D'],'E':['W','C','X','E'],'F':['W','A','X','F']}
CARGO = [('medical',4.5),('water',4),('food',3),('shelter',2)]

def catalog():
    return json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))

def load_preset(scenario_id):
    files = {r['id']:r['file'] for r in catalog()}
    if scenario_id not in files:
        raise ValueError('Unknown scenario_id')
    return json.loads((ROOT/files[scenario_id]).read_text(encoding='utf-8'))

def materialize(config, seed=None):
    c=copy.deepcopy(config)
    if c.get('materialized'):
        if seed is not None and seed != c['seed']:
            raise ValueError('Cannot reseed a resolved input; load the preset first')
        validate(c)
        return c
    c['seed']=c['seed'] if seed is None else seed
    rng=random.Random(c['seed'])
    gen=c['generation']; p=c['parameters']
    if not isinstance(gen['count'],int) or not 0<=gen['count']<=30:
        raise ValueError('Background count must be 0..30')
    edge_lookup={frozenset((e['u'],e['v'])):e for e in c['edges']}
    for i in range(gen['count']):
        site=rng.choice(gen['destinations']); cargo,severity=CARGO[i%4]
        level=0 if gen.get('ordinary_only') else (2 if cargo=='medical' and i%8==0 else (1 if i%3==0 else 0))
        if 'release_batches_s' in gen:
            batches=gen['release_batches_s']
            release=batches[min(len(batches)-1,i*len(batches)//max(1,gen['count']))]
        else:
            release=i*gen['release_step_s']
        route=ROUTES[site]
        duration=0
        for a,b in zip(route,route[1:]):
            edge=edge_lookup[frozenset((a,b))]
            if edge['closed']: raise ValueError('Reference generation route is closed')
            duration+=math.ceil(edge['length_m']/p['speed_m_s'])
        duration+=p['load_s']+p['unload_s']
        duration+=math.ceil(40/p['up_speed_m_s'])+math.ceil(40/p['down_speed_m_s'])+2*p['stabilize_s']
        deadline=release+duration+rng.randint(*gen['deadline_slack_s'])
        c['tasks'].append({'task_id':f'T{i+1:03}','site_id':site,'cargo_type':cargo,
          'release_s':release,'deadline_s':deadline,'expiry_s':deadline+300 if cargo=='medical' else None,
          'level':level,'severity':severity,'quantity_kg':rng.randint(*gen['quantity_kg']),
          'people':rng.randint(20,500)})
    for task in c['tasks']:
        task.setdefault('demand_id',task['task_id'])
    c['tasks'].sort(key=lambda t:(t['release_s'],t['task_id']))
    c['events'].sort(key=lambda e:(e['time_s'],e['event_id']))
    c['materialized']=True
    c['task_count_total']=len(c['tasks'])
    validate(c)
    return c

def validate(c):
    def require(ok,msg):
        if not ok: raise ValueError(msg)
    def unique(rows,key):
        ids=[r[key] for r in rows]
        require(len(ids)==len(set(ids)),f'Duplicate {key}')
        return set(ids)
    def number(v):
        return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    require(c['schema_version']==1,'Unsupported schema')
    require(300<=c['end_s']<=3600,'end_s must be 300..3600')
    nodes=unique(c['nodes'],'node_id'); edges=unique(c['edges'],'edge_id')
    drones=unique(c['drones'],'drone_id'); tasks=unique(c['tasks'],'task_id')
    unique(c['tasks'],'demand_id'); unique(c['events'],'event_id')
    require(1<=len(drones)<=6,'Drone count must be 1..6')
    require(1<=len(tasks)<= (31 if c['scenario_id']=='S09' else 30),'Invalid task count')
    for e in c['edges']:
        require(e['u'] in nodes and e['v'] in nodes,'Unknown edge node')
        require(number(e['length_m']) and e['length_m']>0,'Invalid edge length')
        require(set(e['allowed_layers'])<= {'L1','L2','L3'},'Invalid edge layer')
    for d in c['drones']:
        require(d['node'] in nodes and 0<=d['battery']<=100,'Invalid drone state')
    for t in c['tasks']:
        require(t['site_id'] in nodes,'Unknown task destination')
        require(t['cargo_type'] in c['stock_kg'],'Unknown cargo')
        require(t['level'] in (0,1,2) and number(t['severity']) and 0<=t['severity']<=5,'Invalid urgency')
        require(number(t['quantity_kg']) and t['quantity_kg']>0,'Invalid quantity')
        require(number(t['people']) and t['people']>=0,'Invalid people')
        require(0<=t['release_s']<c['end_s'] and t['release_s']<=t['deadline_s'],'Invalid task timing')
        require(t['expiry_s'] is None or t['expiry_s']>=t['deadline_s'],'Invalid expiry')
    event_targets={'EDGE_CLOSE':edges,'EDGE_OPEN':edges,'SET_ALLOWED_LAYERS':edges,
                   'LINK_LOSS':drones,'CONFIRM_REMOVED':drones,'TASK_CANCEL':tasks}
    for e in c['events']:
        require(e['event_type'] in event_targets,'Unknown event type')
        require(e['target_id'] in event_targets[e['event_type']],'Unknown event target')
        require(0<=e['time_s']<c['end_s'],'Event outside run')
        if e['event_type']=='SET_ALLOWED_LAYERS':
            require(set(e['payload']['layers'])<= {'L1','L2','L3'},'Invalid event layer')
    delivered={}
    stock=copy.deepcopy(c['stock_kg']); lookup={t['task_id']:t for t in c['tasks']}
    unique(c['bootstrap_deliveries'],'delivery_id')
    for b in c['bootstrap_deliveries']:
        require(b['task_id'] in tasks,'Unknown bootstrap task')
        t=lookup[b['task_id']]; kg=b['quantity_kg']
        require(number(kg) and kg>0 and b['time_s']==0,'Invalid bootstrap delivery')
        delivered[t['task_id']]=delivered.get(t['task_id'],0)+kg
        require(delivered[t['task_id']]<=t['quantity_kg'],'Bootstrap overdelivery')
        stock[t['cargo_type']]-=kg
        require(stock[t['cargo_type']]>=0,'Bootstrap stock shortage')
    return True

if __name__=='__main__':
    ap=argparse.ArgumentParser(description='Expand a preset into reproducible input; no simulation is run.')
    ap.add_argument('--scenario',default='S01'); ap.add_argument('--seed',type=int,default=42)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(); resolved=materialize(load_preset(args.scenario),args.seed)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(resolved,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"{resolved['scenario_id']}: {resolved['task_count_total']} tasks, {len(resolved['events'])} events")
