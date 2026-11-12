// Declared synthetic drainage units; NOT a reconstruction of Taipei's sewer network.
// SWMM 5.2.4 documented API. Each executable owns its own DLL state.
using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
partial class SurfaceEngine {
#if UNIX
    const CallingConvention NativeCallingConvention = CallingConvention.Cdecl;
#else
    const CallingConvention NativeCallingConvention = CallingConvention.StdCall;
#endif
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_open(string i,string r,string o);
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_start(int save);
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_step(ref double t);
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_end();
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_report();
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_close();
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_getVersion();
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_getWarnings();
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_getIndex(int kind,string name);
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern double swmm_getValue(int prop,int index);
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern void swmm_setValue(int prop,int index,double value);
    [DllImport("swmm5.dll",CallingConvention=NativeCallingConvention)] static extern int swmm_getMassBalErr(ref float r,ref float f,ref float q);
    class Unit {
        public string id; public int cell,tank,surface,link,drain;
        public double area,cd,crest,toS=0,toN=0,drained=0,maxHead=0;
    }
    List<Unit> units = new List<Unit>();
    double toSurface=0,toNetwork=0,nativeDrain=0,nativeFlood=0;
    double nativeInitial=0,initialSurface=0,exchangeCap=1;
    long exchangeSteps=0;
    void Check(int rc,string op) {if(rc!=0)throw new Exception("SWMM "+op+" error "+rc+"; inspect model.rpt");}
    int Index(int kind,string id) {int i=swmm_getIndex(kind,id);if(i<0)throw new Exception("Missing SWMM object "+id);return i;}
    void ReadUnits(string path) {
        foreach(string line in File.ReadAllLines(path)) {
            if(line.StartsWith("id,") || line.Trim()=="")continue;
            var a=line.Split(',');
            var u=new Unit {id=a[0],cell=int.Parse(a[1]),area=double.Parse(a[2]),cd=double.Parse(a[3]),crest=double.Parse(a[4])};
            if(u.cell<0||u.cell>=count||u.area<=0||u.cd<=0||u.cd>1||Math.Abs(u.crest-z[u.cell])>1e-6)
                throw new Exception("Invalid declared interface "+u.id);
            foreach(Unit prev in units)if(prev.cell==u.cell)throw new Exception("Duplicate interface cell");
            u.tank=Index(2,"T"+u.id);u.surface=Index(2,"S"+u.id);
            u.link=Index(3,"E"+u.id);u.drain=Index(3,"D"+u.id);
            if(swmm_getValue(300,u.tank)!=2||swmm_getValue(300,u.surface)!=1||
               swmm_getValue(400,u.link)!=2||swmm_getValue(402,u.link)!=u.surface)
                throw new Exception("Invalid native interface topology");
            nativeInitial+=swmm_getValue(305,u.tank);
            units.Add(u);
        }
        if(units.Count==0)throw new Exception("No drainage units");
    }
    double StoredNative() {double v=0;foreach(Unit u in units)v+=swmm_getValue(305,u.tank);return v;}
    double SurfaceDt(double limit) {
        double sx=0,sy=0;
        for(int i=0;i<count;i++) {
            vx[i]=h[i]>DRY?qx[i]/h[i]:0;vy[i]=h[i]>DRY?qy[i]/h[i]:0;
            double c=Math.Sqrt(G*h[i]);sx=Math.Max(sx,Math.Abs(vx[i])+c);sy=Math.Max(sy,Math.Abs(vy[i])+c);
        }
        return Math.Min(limit,.4*dx/Math.Max(sx+sy,1e-12));
    }
    void MarkMaximum(int i) {
        if(h[i]>maximum[i]) {maximum[i]=h[i];tmax[i]=time;}
        if(h[i]>.1 && first10[i]<0)first10[i]=time;
    }
    void AdvanceSurface(double stop,int interval) {
        while(time<stop-1e-8) {
            double dt=SurfaceDt(Math.Min(cap,stop-time));
            if(dt<1e-10||double.IsNaN(dt))throw new Exception("Unstable surface dt");
            minDt=Math.Min(minDt,dt);
            Array.Clear(dh,0,count);Array.Clear(dqx,0,count);Array.Clear(dqy,0,count);
            double outward=0;foreach(Face f in faces)outward+=Flux(f);
            for(int i=0;i<count;i++) {
                double old=h[i],nh=old+dt/dx*dh[i],nx=qx[i]+dt/dx*dqx[i],ny=qy[i]+dt/dx*dqy[i];
                if(nh< -1e-10||double.IsNaN(nh)||double.IsInfinity(nh))throw new Exception("Invalid surface depth");
                if(nh<0){correction-=nh*dx*dx;nh=0;}
                double rain=forcing[interval*stations+station[i]]*dt;
                nh+=rain;rainVolume+=rain*dx*dx;
                double removed=Math.Min(nh,loss*dt),frac=nh>DRY?(nh-removed)/nh:0;
                nx*=frac;ny*=frac;nh-=removed;lossVolume+=removed*dx*dx;
                if(nh>DRY) {
                    double speed=Math.Sqrt(nx*nx+ny*ny)/nh;
                    double drag=1+dt*G*roughness*roughness*speed/Math.Pow(nh,4.0/3.0);nx/=drag;ny/=drag;
                }else{nx=0;ny=0;}
                if(double.IsNaN(nx)||double.IsInfinity(nx)||double.IsNaN(ny)||double.IsInfinity(ny))
                    throw new Exception("Invalid momentum");
                h[i]=nh;qx[i]=nx;qy[i]=ny;
                if(nh>maximum[i]){maximum[i]=nh;tmax[i]=time+dt;}
                if(old>.1&&nh>.1)duration10[i]+=dt;
                else if(old<=.1&&nh>.1) {
                    double crossing=dt*(.1-old)/(nh-old);duration10[i]+=dt-crossing;
                    if(first10[i]<0)first10[i]=time+crossing;
                }else if(old>.1&&nh<=.1)duration10[i]+=dt*(old-.1)/(old-nh);
            }
            outVolume+=outward*dx*dt;time+=dt;steps++;
        }
        time=stop;
    }
    double ExchangeDt(double capTime) {
        double dt=capTime;
        foreach(Unit u in units) {
            double depth=h[u.cell],head=swmm_getValue(304,u.tank);
            // Close a dry exchange until rain arrives. Does not erase water.
            bool on=depth>1e-6||head>2+1e-6;
            swmm_setValue(407,u.link,on?1:0);
            if(on&&depth>1e-6) {
                double qbound=u.cd*u.area*Math.Sqrt(2*G*depth);
                dt=Math.Min(dt,.8*depth*dx*dx/qbound);
            }
        }
        dt=Math.Floor((dt+1e-9)*1000)/1000;
        if(dt<.001)throw new Exception("Exchange step below native 1 ms; result rejected");
        return dt;
    }
    void Exchange(double dt,StreamWriter forcingLog) {
        // Independent reservoirs use their own local datum: base 0, surface 2 m.
        foreach(Unit u in units)swmm_setValue(304,u.surface,2+h[u.cell]);
        swmm_setValue(3,0,dt);
        if(Math.Abs(swmm_getValue(3,0)-dt)>1e-8)throw new Exception("Native routing step changed");
        double elapsed=0;Check(swmm_step(ref elapsed),"step");
        double target=Math.Round(time+dt,3);
        if(elapsed==0 ? target<end-.001 : Math.Abs(elapsed*86400-target)>.0011)
            throw new Exception("Surface/native clocks disagree: target="+target+" native="+(elapsed*86400)+" dt="+dt);
        double toS=0,toN=0,drain=0;
        foreach(Unit u in units) {
            int i=u.cell;double q=swmm_getValue(410,u.link),v=q*dt,old=h[i],next=old+v/(dx*dx);
            if(double.IsNaN(q)||double.IsInfinity(q)||next< -1e-12)throw new Exception("Exchange overdrew water; no clipping");
            // Any floating-point negative is recorded, never hidden.
            if(next<0){correction-=next*dx*dx;next=0;}
            if(v<0) {double frac=old>0?next/old:0;qx[i]*=frac;qy[i]*=frac;u.toN-=v;toN-=v;}
            else {u.toS+=v;toS+=v;}
            h[i]=next;MarkMaximum(i);
            double dv=swmm_getValue(410,u.drain)*dt;
            if(dv< -1e-8)throw new Exception("Unexpected reverse outlet flow");
            drain+=dv;u.drained+=dv;
            nativeFlood+=swmm_getValue(308,u.tank)*dt;
            u.maxHead=Math.Max(u.maxHead,swmm_getValue(304,u.tank)-2);
        }
        toSurface+=toS;toNetwork+=toN;nativeDrain+=drain;exchangeSteps++;
        forcingLog.WriteLine(string.Join(",",new object[]{time,dt,toS,toN,drain,StoredNative()}));
    }
    void CoupledHistory(StreamWriter w) {
        double stored=0,local=0,a=0,peak=0;
        for(int i=0;i<count;i++) {
            stored+=h[i]*dx*dx;
            if(report[i]){local+=h[i]*dx*dx;if(h[i]>.1)a+=dx*dx;peak=Math.Max(peak,h[i]);}
        }
        w.WriteLine(string.Join(",",new object[]{time,stored,local,a/1e6,peak,rainVolume,lossVolume,outVolume,
            toNetwork,toSurface,nativeDrain,StoredNative(),exchangeSteps,steps}));
        w.Flush();
        string tmp=Path.Combine(output,"progress.tmp"),dest=Path.Combine(output,"progress.json");
        File.WriteAllText(tmp,"{\"time_s\":"+time+",\"end_s\":"+end+",\"exchange_steps\":"+exchangeSteps+"}");
        if(File.Exists(dest))File.Replace(tmp,dest,null);else File.Move(tmp,dest);
    }
    void CoupledRun(string inp,string unitPath) {
        Directory.CreateDirectory(output);
        if(swmm_getVersion()!=52004)throw new Exception("Only tested SWMM 5.2.4 is accepted");
        bool started=false;
        try {
            Check(swmm_open(inp,Path.ChangeExtension(inp,"rpt"),Path.ChangeExtension(inp,"out")),"open");
            Check(swmm_start(1),"start");started=true;ReadUnits(unitPath);
            if(swmm_getWarnings()!=0)throw new Exception("Native setup warnings; inspect model.rpt before running");
            foreach(double d in h)initialSurface+=d*dx*dx;
            string capFile=Path.Combine(output,"exchange_cap.txt");
            if(File.Exists(capFile))exchangeCap=double.Parse(File.ReadAllText(capFile));
            if(exchangeCap<.001||exchangeCap>5)throw new Exception("Invalid exchange cap");
            var timer=System.Diagnostics.Stopwatch.StartNew();
            using(var log=new StreamWriter(Path.Combine(output,"history.csv")))
            using(var forcingLog=new StreamWriter(Path.Combine(output,"exchange.csv"))) {
                log.WriteLine("time_s,surface_stored_m3,xinyi_stored_m3,xinyi_area_gt10_km2,xinyi_max_depth_m,rain_m3,infiltration_m3,boundary_out_m3,to_network_m3,to_surface_m3,drain_m3,native_stored_m3,exchange_steps,surface_steps");
                forcingLog.WriteLine("t_start_s,dt_s,to_surface_m3,to_network_m3,drain_m3,native_stored_m3");
                CoupledHistory(log);int interval=0;double nextLog=Math.Min(60,end);
                while(time<end-1e-8) {
                    if(File.Exists(Path.Combine(output,"cancel.flag")))throw new OperationCanceledException("Cancelled by user");
                    if(timer.Elapsed.TotalHours>2)throw new TimeoutException("Run exceeded safety timeout");
                    while(interval<intervals-1&&time>=edges[interval+1]-1e-8)interval++;
                    double dt=ExchangeDt(Math.Min(exchangeCap,Math.Min(edges[interval+1]-time,nextLog-time)));
                    double stop=Math.Round(time+dt,3);
                    Exchange(dt,forcingLog);
                    AdvanceSurface(stop,interval);
                    if(time>=nextLog-1e-8) {
                        CoupledHistory(log);nextLog=Math.Min(nextLog+60,end);
                        if(Math.Abs(time%600)<1e-6)Console.WriteLine("PROGRESS "+time+"/"+end+" wall="+timer.Elapsed.TotalSeconds.ToString("F1"));
                    }
                }
            }
            double nativeFinal=StoredNative(),surfaceFinal=0;foreach(double d in h)surfaceFinal+=d*dx*dx;
            Check(swmm_end(),"end");started=false;
            float runoff=0,flow=0,quality=0;Check(swmm_getMassBalErr(ref runoff,ref flow,ref quality),"balance");
            int warnings=swmm_getWarnings();Check(swmm_report(),"report");
            using(var w=new BinaryWriter(File.Create(Path.Combine(output,"state.bin"))))
                foreach(var v in new double[][]{h,qx,qy,maximum,tmax,first10,duration10})foreach(double d in v)w.Write(d);
            using(var w=new StreamWriter(Path.Combine(output,"units_result.csv"))) {
                w.WriteLine("id,to_network_m3,to_surface_m3,drained_m3,max_head_above_surface_m");
                foreach(Unit u in units)w.WriteLine(string.Join(",",new object[]{u.id,u.toN,u.toS,u.drained,u.maxHead}));
            }
            double surfaceResidual=initialSurface+rainVolume-lossVolume-outVolume+toSurface-toNetwork+correction-surfaceFinal;
            double residual=initialSurface+nativeInitial+rainVolume-lossVolume-outVolume-nativeDrain-nativeFlood+correction-surfaceFinal-nativeFinal;
            using(var w=new StreamWriter(Path.Combine(output,"balance.csv"))) {
                w.WriteLine("initial_surface_m3,initial_native_m3,rain_m3,infiltration_m3,boundary_out_m3,to_network_m3,to_surface_m3,drain_m3,surface_stored_m3,native_stored_m3,native_flood_m3,roundoff_m3,surface_residual_m3,combined_residual_m3,native_flow_error_pct,warnings,time_s,exchange_steps,surface_steps,wall_s");
                w.WriteLine(string.Join(",",new object[]{initialSurface,nativeInitial,rainVolume,lossVolume,outVolume,toNetwork,toSurface,
                    nativeDrain,surfaceFinal,nativeFinal,nativeFlood,correction,surfaceResidual,residual,flow,warnings,time,exchangeSteps,steps,timer.Elapsed.TotalSeconds}));
            }
            Console.WriteLine("COMPLETED_COUPLED "+output);
        }finally {if(started)swmm_end();swmm_close();}
    }
}
