// Optimized port of the project's NumPy HLL/hydrostatic-reconstruction solver.
// SI units; y velocity follows raster rows (southward for a north-up raster).
// This is a scenario surface model, NOT SWMM or a resolved sewer model.
using System;
using System.IO;
using System.Collections.Generic;
using System.Globalization;
partial class SurfaceEngine {
    const double G=9.81, DRY=1e-8;
    int count, stations, intervals;
    double dx, roughness, cap, end, loss, time=0;
    bool closed;
    double[] z,h,qx,qy,dh,dqx,dqy,vx,vy,maximum,tmax,first10,duration10,edges,forcing;
    int[] station;
    bool[] report;
    struct Face { public int a,b,axis; public Face(int a,int b,int axis) {this.a=a;this.b=b;this.axis=axis;} }
    List<Face> faces = new List<Face>();
    double rainVolume=0, lossVolume=0, outVolume=0, correction=0, minDt=double.PositiveInfinity;
    long steps=0;
    string output;
    double[] ReadDoubles(BinaryReader r,int n) {var v=new double[n];for(int i=0;i<n;i++)v[i]=r.ReadDouble();return v;}
    void Load(string path) {
        using(var r=new BinaryReader(File.OpenRead(path))) {
            if(r.ReadInt32()!=20261020)throw new Exception("Wrong binary contract");
            count=r.ReadInt32(); dx=r.ReadDouble(); roughness=r.ReadDouble(); cap=r.ReadDouble();
            closed=r.ReadBoolean(); loss=r.ReadDouble(); stations=r.ReadInt32(); intervals=r.ReadInt32();
            edges=ReadDoubles(r,intervals+1); end=edges[intervals]; forcing=ReadDoubles(r,intervals*stations);
            z=ReadDoubles(r,count); h=ReadDoubles(r,count); qx=ReadDoubles(r,count); qy=ReadDoubles(r,count);
            station=new int[count]; report=new bool[count];
            for(int i=0;i<count;i++)station[i]=r.ReadInt32();
            for(int i=0;i<count;i++)report[i]=r.ReadBoolean();
            int nf=r.ReadInt32();
            for(int i=0;i<nf;i++) faces.Add(new Face(r.ReadInt32(),r.ReadInt32(),r.ReadInt32()));
            if(r.BaseStream.Position!=r.BaseStream.Length)throw new Exception("Trailing data");
        }
        dh=new double[count];dqx=new double[count];dqy=new double[count];vx=new double[count];vy=new double[count];
        maximum=(double[])h.Clone();tmax=new double[count];first10=new double[count];duration10=new double[count];
        for(int i=0;i<count;i++) first10[i]=h[i]>.1?0:-1;
        if(dx<=0 || cap<=0 || roughness<0 || loss<0 || stations<1 || intervals<1)throw new Exception("Invalid input");
        for(int k=0;k<intervals;k++)if(edges[k+1]<=edges[k])throw new Exception("Bad edges");
        foreach(double v in forcing)if(v<0 || double.IsNaN(v) || double.IsInfinity(v))throw new Exception("Invalid rain");
        for(int i=0;i<count;i++)if(station[i]<0||station[i]>=stations||h[i]<0)throw new Exception("Invalid cell");
    }
    double Flux(Face f) {
        int a=f.a,b=f.b,axis=f.axis;
        int ia=a>=0?a:b, ib=b>=0?b:a;
        double ha=h[ia],hb=h[ib],za=z[ia],zb=z[ib];
        double ax=vx[ia],ay=vy[ia],bx=vx[ib],by=vy[ib];
        if(a<0) {
            if(axis==0) ax=closed?-bx:Math.Min(bx,0);
            else ay=closed?-by:Math.Min(by,0);
        }
        if(b<0) {
            if(axis==0) bx=closed?-ax:Math.Max(ax,0);
            else by=closed?-ay:Math.Max(ay,0);
        }
        double crest=Math.Max(za,zb),hl=Math.Max(0,ha+za-crest),hr=Math.Max(0,hb+zb-crest);
        double an=axis==0?ax:ay,bn=axis==0?bx:by;
        double cl=Math.Sqrt(G*hl),cr=Math.Sqrt(G*hr);
        double sl=Math.Min(0,Math.Min(an-cl,bn-cr)),sr=Math.Max(0,Math.Max(an+cl,bn+cr));
        double fh=0,fx=0,fy=0,den=sr-sl;
        if(den>1e-12) {
            fh=(sr*hl*an-sl*hr*bn+sl*sr*(hr-hl))/den;
            fx=(sr*(hl*ax*an+(axis==0?.5*G*hl*hl:0))
                -sl*(hr*bx*bn+(axis==0?.5*G*hr*hr:0))+sl*sr*(hr*bx-hl*ax))/den;
            fy=(sr*(hl*ay*an+(axis==1?.5*G*hl*hl:0))
                -sl*(hr*by*bn+(axis==1?.5*G*hr*hr:0))+sl*sr*(hr*by-hl*ay))/den;
        }
        if(!closed && ((a<0 && fh>0)||(b<0 && fh<0)))return 0;
        if(a>=0) {
            dh[a]-=fh;dqx[a]-=fx+(axis==0?.5*G*(ha*ha-hl*hl):0);
            dqy[a]-=fy+(axis==1?.5*G*(ha*ha-hl*hl):0);
        }
        if(b>=0) {
            dh[b]+=fh;dqx[b]+=fx+(axis==0?.5*G*(hb*hb-hr*hr):0);
            dqy[b]+=fy+(axis==1?.5*G*(hb*hb-hr*hr):0);
        }
        return b<0?fh:(a<0?-fh:0);
    }
    void WriteRow(StreamWriter w) {
        double stored=0,local=0,area10=0,area30=0,max=0;
        for(int i=0;i<count;i++) {
            stored+=h[i]*dx*dx;
            if(report[i]) {local+=h[i]*dx*dx;if(h[i]>.1)area10+=dx*dx;if(h[i]>.3)area30+=dx*dx;max=Math.Max(max,h[i]);}
        }
        w.WriteLine(string.Join(",",new object[]{time,stored,local,area10/1e6,area30/1e6,max,rainVolume,lossVolume,outVolume,correction,steps}));
        w.Flush();
    }
    void Run() {
        Directory.CreateDirectory(output);
        double initial=0;foreach(double d in h)initial+=d*dx*dx;
        var timer=System.Diagnostics.Stopwatch.StartNew();
        using(var log=new StreamWriter(Path.Combine(output,"history.csv"))) {
            log.WriteLine("time_s,domain_stored_m3,xinyi_stored_m3,xinyi_area_gt10_km2,xinyi_area_gt30_km2,xinyi_max_depth_m,rain_m3,loss_m3,boundary_out_m3,roundoff_added_m3,steps");
            WriteRow(log);int interval=0;double nextLog=Math.Min(60,end);
            while(time<end-1e-8) {
                while(interval<intervals-1 && time>=edges[interval+1]-1e-8)interval++;
                double sx=0,sy=0;
                for(int i=0;i<count;i++) {
                    vx[i]=h[i]>DRY?qx[i]/h[i]:0;vy[i]=h[i]>DRY?qy[i]/h[i]:0;
                    double c=Math.Sqrt(G*h[i]);sx=Math.Max(sx,Math.Abs(vx[i])+c);sy=Math.Max(sy,Math.Abs(vy[i])+c);
                }
                double dt=Math.Min(Math.Min(cap,.4*dx/Math.Max(sx+sy,1e-12)),Math.Min(edges[interval+1]-time,nextLog-time));
                if(dt<1e-10||double.IsNaN(dt))throw new Exception("Unstable dt at "+time);
                minDt=Math.Min(minDt,dt);
                Array.Clear(dh,0,count);Array.Clear(dqx,0,count);Array.Clear(dqy,0,count);
                double outward=0;foreach(Face f in faces)outward+=Flux(f);
                for(int i=0;i<count;i++) {
                    double old=h[i], nh=h[i]+dt/dx*dh[i];
                    double nx=qx[i]+dt/dx*dqx[i],ny=qy[i]+dt/dx*dqy[i];
                    if(nh< -1e-10||double.IsNaN(nh)||double.IsInfinity(nh))throw new Exception("Negative/nonfinite depth at "+time+": "+nh);
                    if(nh<0) {correction-=nh*dx*dx;nh=0;}
                    double rain=forcing[interval*stations+station[i]]*dt;
                    nh+=rain;rainVolume+=rain*dx*dx;
                    double removed=Math.Min(nh,loss*dt),frac=nh>DRY?(nh-removed)/nh:0;
                    nx*=frac;ny*=frac;nh-=removed;lossVolume+=removed*dx*dx;
                    if(nh>DRY) {
                        double speed=Math.Sqrt(nx*nx+ny*ny)/nh;
                        double friction=1+dt*G*roughness*roughness*speed/Math.Pow(nh,4.0/3.0);
                        nx/=friction;ny/=friction;
                    } else {nx=0;ny=0;}
                    if(double.IsNaN(nx)||double.IsInfinity(nx)||double.IsNaN(ny)||double.IsInfinity(ny))throw new Exception("Bad momentum");
                    h[i]=nh;qx[i]=nx;qy[i]=ny;
                    if(nh>maximum[i]) {maximum[i]=nh;tmax[i]=time+dt;}
                    if(old>.1&&nh>.1)duration10[i]+=dt;
                    else if(old<=.1&&nh>.1) {
                        double crossing=dt*(.1-old)/(nh-old);
                        duration10[i]+=dt-crossing;
                        if(first10[i]<0)first10[i]=time+crossing;
                    } else if(old>.1&&nh<=.1) duration10[i]+=dt*(old-.1)/(old-nh);
                }
                outVolume+=outward*dx*dt;time+=dt;steps++;
                if(time>=nextLog-1e-8) {
                    WriteRow(log); nextLog=Math.Min(nextLog+60,end);
                    if(Math.Abs(time%1800)<1e-6)Console.WriteLine("t="+time+"s steps="+steps+" elapsed="+timer.Elapsed.TotalSeconds.ToString("F1")+"s");
                }
            }
        }
        using(var w=new BinaryWriter(File.Create(Path.Combine(output,"state.bin"))))
            foreach(var v in new double[][]{h,qx,qy,maximum,tmax,first10,duration10}) foreach(double x in v)w.Write(x);
        double storedFinal=0;foreach(double x in h)storedFinal+=x*dx*dx;
        using(var w=new StreamWriter(Path.Combine(output,"balance.csv"))) {
            w.WriteLine("initial_m3,rain_m3,loss_m3,boundary_out_m3,stored_m3,roundoff_added_m3,residual_m3,time_s,steps,min_dt_s,wall_s");
            w.WriteLine(string.Join(",",new object[]{initial,rainVolume,lossVolume,outVolume,storedFinal,correction,
                initial+rainVolume-lossVolume-outVolume+correction-storedFinal,time,steps,minDt,timer.Elapsed.TotalSeconds}));
        }
        Console.WriteLine("COMPLETED "+output);
    }
    static int Main(string[] args) {
        CultureInfo.CurrentCulture=CultureInfo.InvariantCulture;
        try {
            var s=new SurfaceEngine();s.output=args[1];s.Load(args[0]);
            if(args.Length>2)s.CoupledRun(args[2],args[3]);else s.Run();
            return 0;
        }
        catch(Exception e){Console.Error.WriteLine(e);return 1;}
    }
}
