"""Experimental 2D Saint-Venant finite-volume solver, SI units.

First-order HLL flux + Audusse et al. (2004) hydrostatic reconstruction.
Raster with explicit active cells, CFL step, semi-implicit Manning friction.
This is our implementation, NOT EPA SWMM's own 2D solver or LISFLOOD-FP.
Reference: https://doi.org/10.1137/S1064827503431090
No invented terrain, loss, boundary or inlet defaults for site models.
"""
import numpy as np

G = 9.81
DRY = 1e-8


def velocity(u):
    h = u[0]
    return np.divide(u[1:], h[None], out=np.zeros_like(u[1:]), where=h[None] > DRY)


def face_flux(left, right, zleft, zright, normal):
    """Returns flux as seen by left/right cells; momentum corrections differ."""
    vl, vr = velocity(left), velocity(right)
    crest = np.maximum(zleft, zright)
    hl = np.maximum(0., left[0]+zleft-crest)
    hr = np.maximum(0., right[0]+zright-crest)
    ul = np.concatenate((hl[None], vl*hl[None]), axis=0)
    ur = np.concatenate((hr[None], vr*hr[None]), axis=0)
    fl, fr = ul*vl[normal], ur*vr[normal]
    fl[normal+1] += .5*G*hl**2
    fr[normal+1] += .5*G*hr**2
    sl = np.minimum(np.minimum(vl[normal]-np.sqrt(G*hl), vr[normal]-np.sqrt(G*hr)), 0.)
    sr = np.maximum(np.maximum(vl[normal]+np.sqrt(G*hl), vr[normal]+np.sqrt(G*hr)), 0.)
    denom = sr-sl
    flux = np.divide(sr[None]*fl-sl[None]*fr+(sl*sr)[None]*(ur-ul), denom[None],
                     out=np.zeros_like(ul), where=denom[None] > 1e-12)
    left_flux, right_flux = flux.copy(), flux.copy()
    left_flux[normal+1] += .5*G*(left[0]**2-hl**2)
    right_flux[normal+1] += .5*G*(right[0]**2-hr**2)
    return left_flux, right_flux


class Surface:
    def __init__(self, terrain, dx, manning, boundary='closed', cfl=0.4,
                 active_mask=None, mask_boundary=None):
        terrain = np.asarray(terrain, dtype=np.float64)
        if terrain.ndim != 2 or not terrain.size:
            raise ValueError('terrain must be a nonempty 2D grid')
        if active_mask is None:
            self.active = np.ones(terrain.shape, dtype=bool)
        else:
            mask = np.asarray(active_mask)
            if mask.shape != terrain.shape or mask.dtype != np.bool_ or not mask.any():
                raise ValueError('active_mask must be a nonempty boolean grid matching terrain')
            self.active = mask.copy()
        if not self.active.all() and mask_boundary not in ('closed', 'open_outflow'):
            raise ValueError('explicit mask_boundary required; polygon edge is not automatically a divide')
        if not np.isfinite(terrain[self.active]).all():
            raise ValueError('active terrain must be finite; do not fill missing elevations')
        # Zero here is only unused memory, never a physical elevation or wet cell.
        self.z = np.where(self.active, terrain, 0.)
        self.active.setflags(write=False)
        self.mask_boundary = mask_boundary
        if not np.isfinite(dx) or dx <= 0 or not 0 < cfl <= .45:
            raise ValueError('invalid grid spacing or CFL')
        if boundary not in ('closed','open_outflow'):
            raise ValueError('unsupported boundary')
        self.dx, self.cfl, self.boundary = float(dx), cfl, boundary
        n = np.broadcast_to(np.asarray(manning, dtype=float), self.z.shape)
        if np.any(n[self.active] < 0) or not np.isfinite(n[self.active]).all():
            raise ValueError('invalid Manning coefficient')
        self.n = np.where(self.active, n, 0.)
        self.u = np.zeros((3, *self.z.shape), dtype=np.float64)
        self.time = self.rain_volume = self.loss_volume = self.out_volume = self.roundoff_volume = 0.
        self.steps = 0

    @property
    def depth(self):
        return self.u[0]

    @property
    def volume(self):
        return float(self.depth.sum()*self.dx**2)

    def stable_dt(self, cap):
        if not np.isfinite(cap) or cap <= 0:
            raise ValueError('time step cap must be finite and positive')
        if not np.isfinite(self.u).all() or np.any(self.depth < 0):
            raise ValueError('invalid surface state')
        if np.any(self.u[:, ~self.active] != 0):
            raise ValueError('inactive cells cannot contain water or momentum')
        vel = velocity(self.u)
        c = np.sqrt(G*self.depth)
        speed = np.max(abs(vel[0])+c) + np.max(abs(vel[1])+c)
        return min(float(cap), self.cfl*self.dx/max(speed, 1e-12))

    def _face_fluxes(self, normal):
        """Reflective or one-way zero-gradient ghost at each active-domain edge.

        Internal holes and disconnected parts obey mask_boundary, while the
        rectangular array edge obeys boundary. No flux is passed to inactive cells.
        Momentum wall pressure is retained on the active side for lake-at-rest.
        """
        p = np.pad(self.u, ((0,0),(1,1),(1,1)), mode='edge')
        z = np.pad(self.z, 1, mode='edge')
        active = np.pad(self.active, 1, constant_values=False)
        if normal == 0:
            ls, rs = (slice(1,-1),slice(None,-1)), (slice(1,-1),slice(1,None))
        else:
            ls, rs = (slice(None,-1),slice(1,-1)), (slice(1,None),slice(1,-1))
        left, right = p[(slice(None),)+ls].copy(), p[(slice(None),)+rs].copy()
        zl, zr = z[ls].copy(), z[rs].copy()
        al, ar = active[ls], active[rs]
        left_only, right_only = al & ~ar, ar & ~al
        walls = np.full(al.shape, self.mask_boundary == 'closed', dtype=bool)
        if normal == 0:
            walls[:,[0,-1]] = self.boundary == 'closed'
        else:
            walls[[0,-1],:] = self.boundary == 'closed'
        right[:,left_only] = left[:,left_only]; zr[left_only] = zl[left_only]
        left[:,right_only] = right[:,right_only]; zl[right_only] = zr[right_only]
        right[normal+1,left_only & walls] *= -1
        left[normal+1,right_only & walls] *= -1
        # At an open edge, the outside ghost cannot supply inward momentum.
        right[normal+1,left_only & ~walls] = np.maximum(right[normal+1,left_only & ~walls],0)
        left[normal+1,right_only & ~walls] = np.minimum(left[normal+1,right_only & ~walls],0)
        fl, fr = face_flux(left,right,zl,zr,normal)
        suppress = (~al & ~ar) | (left_only & ~walls & (fl[0]<0)) | (right_only & ~walls & (fr[0]>0))
        fl[:,suppress] = 0.; fr[:,suppress] = 0.
        outward = float(fl[0,left_only].sum()-fr[0,right_only].sum())
        return fl,fr,outward

    def step(self, dt, rain_m_s=0., loss_capacity_m_s=0.):
        if not np.isfinite(dt) or dt <= 0 or dt > self.stable_dt(dt)+1e-12:
            raise ValueError('step violates CFL')
        rain = np.broadcast_to(np.asarray(rain_m_s, dtype=float), self.z.shape)
        loss = np.broadcast_to(np.asarray(loss_capacity_m_s, dtype=float), self.z.shape)
        if (not np.isfinite(rain[self.active]).all() or not np.isfinite(loss[self.active]).all()
                or np.any(rain[self.active]<0) or np.any(loss[self.active]<0)):
            raise ValueError('forcing must be finite nonnegative rates, missing is not zero')
        rain, loss = np.where(self.active,rain,0.), np.where(self.active,loss,0.)
        xl,xr,xout = self._face_fluxes(0)
        yl,yr,yout = self._face_fluxes(1)
        net_out = (xout+yout)*self.dx*dt
        new = self.u-dt/self.dx*(xl[:,:,1:]-xr[:,:,:-1]+yl[:,1:,:]-yr[:,:-1,:])
        new[:,~self.active] = 0.
        if not np.isfinite(new).all() or new[0].min() < -1e-10:
            raise FloatingPointError(f'nonfinite/negative depth at t={self.time}, dt={dt}, min={new[0].min()}')
        correction = -np.minimum(new[0],0.)
        self.roundoff_volume += float(correction.sum()*self.dx**2)
        new[0] += correction
        new[0] += rain*dt
        removed = np.minimum(new[0], loss*dt)
        fraction = np.divide(new[0]-removed,new[0],out=np.zeros_like(new[0]),where=new[0]>DRY)
        new[1:] *= fraction[None]
        new[0] -= removed
        h = new[0]
        v = velocity(new)
        speed = np.sqrt((v**2).sum(axis=0))
        friction = 1+dt*G*self.n**2*speed/np.maximum(h,DRY)**(4/3)
        new[1:] /= friction[None]
        new[1:,h<=DRY] = 0.
        self.u = new
        self.rain_volume += float(rain.sum()*self.dx**2*dt)
        self.loss_volume += float(removed.sum()*self.dx**2)
        self.out_volume += float(net_out)
        self.time += dt; self.steps += 1
        return dt

    def advance(self, duration, rain_m_s=0., loss_capacity_m_s=0., dt_cap=5.):
        if not np.isfinite(duration) or duration < 0 or not np.isfinite(dt_cap) or dt_cap <= 0:
            raise ValueError('duration must be finite nonnegative and dt_cap finite positive')
        end = self.time + duration
        while self.time < end-1e-10:
            self.step(self.stable_dt(min(dt_cap,end-self.time)),rain_m_s,loss_capacity_m_s)

    def balance(self, initial_volume=0., net_exchange_volume=0.):
        expected = initial_volume+self.rain_volume-self.loss_volume-self.out_volume+net_exchange_volume+self.roundoff_volume
        return {'initial_m3':initial_volume,'rain_m3':self.rain_volume,'loss_m3':self.loss_volume,
                'boundary_out_m3':self.out_volume,'net_exchange_m3':net_exchange_volume,
                'roundoff_added_m3':self.roundoff_volume,'stored_m3':self.volume,
                'residual_m3':expected-self.volume,'time_s':self.time,'steps':self.steps}
