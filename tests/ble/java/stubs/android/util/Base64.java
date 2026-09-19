package android.util;

public final class Base64 {
    public static byte[] decode(String s, int flags) {
        return java.util.Base64.getDecoder().decode(s);
    }
}
