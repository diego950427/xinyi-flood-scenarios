"""Strict read-only parser for SWMM 5.2.4 binary result layout (CMS only).

Reference: USEPA/Stormwater-Management-Model v5.2.4 src/solver/output.c
Counts and variable codes are read from the file, not guessed from object counts.
"""
from pathlib import Path
import struct
import numpy as np


def read_output(path):
    data=Path(path).read_bytes()
    if len(data)<100: raise ValueError('truncated SWMM output')
    magic,version,units,ns,nn,nl,npoll=struct.unpack_from('<7i',data)
    idpos,inpos,outpos,nperiods,error,endmagic=struct.unpack_from('<6i',data,len(data)-24)
    if magic!=516114522 or endmagic!=magic or version!=52004 or units!=3 or error!=0:
        raise ValueError('unsupported version/units or failed native output')
    if min(ns,nn,nl,npoll,nperiods)<0 or not 28<=idpos<inpos<outpos<len(data)-24:
        raise ValueError('invalid counts or offsets')
    pos=idpos
    names=[]
    for count in [ns,nn,nl,npoll]:
        group=[]
        for _ in range(count):
            size=struct.unpack_from('<i',data,pos)[0]; pos+=4
            if not 0<size<=1024 or pos+size>inpos: raise ValueError('invalid object name')
            group.append(data[pos:pos+size].decode('utf-8')); pos+=size
        names.append(group)
    if pos+4*npoll!=inpos: raise ValueError('ID metadata length mismatch')
    pos=inpos
    for count in [ns,nn,nl]:
        props=struct.unpack_from('<i',data,pos)[0]; pos+=4
        if not 0<props<20: raise ValueError('invalid input property count')
        pos+=4*props*(count+1)
    codes=[]
    for _ in range(4):
        count=struct.unpack_from('<i',data,pos)[0]; pos+=4
        if not 0<count<10000: raise ValueError('invalid output property count')
        codes.append(list(struct.unpack_from('<'+'i'*count,data,pos))); pos+=4*count
    start,report_step=struct.unpack_from('<di',data,pos); pos+=12
    if pos!=outpos or report_step<=0: raise ValueError('output metadata length mismatch')
    size=8+4*(ns*len(codes[0])+nn*len(codes[1])+nl*len(codes[2])+len(codes[3]))
    if outpos+nperiods*size!=len(data)-24: raise ValueError('missing or excess output periods')
    times=np.ndarray((nperiods,),dtype='<f8',buffer=data,offset=outpos,strides=(size,)).copy()
    arrays=[]; offset=outpos+8
    for count,groupcodes in zip([ns,nn,nl,1],codes):
        arrays.append(np.ndarray((nperiods,count,len(groupcodes)),dtype='<f4',buffer=data,
            offset=offset,strides=(size,len(groupcodes)*4,4)).copy())
        offset+=count*len(groupcodes)*4
    if not np.isfinite(times).all() or any(not np.isfinite(a).all() for a in arrays):
        raise ValueError('nonfinite native results')
    raw_elapsed=(times-start)*86400
    # SWMM 5.2.4 swmm5.c getDateTime explicitly adds 1 ms before encoding dates.
    # Preserve the raw dates, remove this documented formatting bias for the clock.
    elapsed=raw_elapsed-.001
    if nperiods and np.max(abs(elapsed-np.arange(1,nperiods+1)*report_step))>.00001:
        raise ValueError(f'incomplete native report clock: start={start}, first={elapsed[:3]}, last={elapsed[-1]}, step={report_step}')
    return {'times_s':elapsed,'raw_encoded_times_s':raw_elapsed,'names':names,'codes':codes,
            'subcatchments':arrays[0],'nodes':arrays[1],'links':arrays[2],'system':arrays[3][:,0,:],
            'periods':nperiods,'report_step_s':report_step,'version':version}
