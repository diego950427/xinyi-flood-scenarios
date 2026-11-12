// Verify the real managed native-file entry guard without calling a solver.
using System;
using System.IO;
using System.Reflection;
using System.Text;
class NativePathProbe {
    static MethodInfo method;
    static string ConvertPath(string path) {return (string)method.Invoke(null,new object[]{path});}
    static bool Rejects(string path) {
        try {ConvertPath(path);return false;}
        catch(TargetInvocationException error) {return error.InnerException is ArgumentException;}
    }
    static int Main(string[] args) {
        var assembly=Assembly.LoadFrom(args[0]);
        method=assembly.GetType("SurfaceEngine").GetMethod("NativePath",BindingFlags.Static|BindingFlags.NonPublic);
        string prefix=Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        int prefixBytes=Encoding.UTF8.GetByteCount(prefix);
        string exact=prefix+new string('a',259-prefixBytes);
        bool shortAscii=ConvertPath("model.inp")==Path.GetFullPath("model.inp");
        bool shortUnicode=ConvertPath("雨量.inp")==Path.GetFullPath("雨量.inp");
        bool exactAccepted=ConvertPath(exact)==exact;
        bool longAsciiRejected=Rejects(exact+"a");
        bool unicodeBytesRejected=Rejects(prefix+new string('測',90)+".inp");
        bool all=shortAscii&&shortUnicode&&exactAccepted&&longAsciiRejected&&unicodeBytesRejected;
        Console.WriteLine("{\"passed\":"+all.ToString().ToLowerInvariant()+
            ",\"relative_ascii\":"+shortAscii.ToString().ToLowerInvariant()+
            ",\"relative_unicode\":"+shortUnicode.ToString().ToLowerInvariant()+
            ",\"exact_259_bytes\":"+exactAccepted.ToString().ToLowerInvariant()+
            ",\"reject_260_bytes\":"+longAsciiRejected.ToString().ToLowerInvariant()+
            ",\"reject_shorter_unicode_over_byte_limit\":"+unicodeBytesRejected.ToString().ToLowerInvariant()+"}");
        return all?0:1;
    }
}
