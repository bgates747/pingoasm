
import org.apache.commons.imaging.color.ColorConversions;
import org.apache.commons.imaging.color.ColorHsv;

import java.awt.image.BufferedImage;

public class AgonColors {

    private static final int[] colors64 = {
        0xFF000000, // 0
        0xFFAA0000, // 1
        0xFF00AA00, // 2
        0xFFAAAA00, // 3
        0xFF0000AA, // 4
        0xFFAA00AA, // 5
        0xFF00AAAA, // 6
        0xFFAAAAAA, // 7
        0xFF555555, // 8
        0xFFFF0000, // 9
        0xFF00FF00, // 10
        0xFFFFFF00, // 11
        0xFF0000FF, // 12
        0xFFFF00FF, // 13
        0xFF00FFFF, // 14
        0xFFFFFFFF, // 15
        0xFF000055, // 16
        0xFF005500, // 17
        0xFF005555, // 18
        0xFF0055AA, // 19
        0xFF0055FF, // 20
        0xFF00AA55, // 21
        0xFF00AAFF, // 22
        0xFF00FF55, // 23
        0xFF00FFAA, // 24
        0xFF550000, // 25
        0xFF550055, // 26
        0xFF5500AA, // 27
        0xFF5500FF, // 28
        0xFF555500, // 29
        0xFF5555AA, // 30
        0xFF5555FF, // 31
        0xFF55AA00, // 32
        0xFF55AA55, // 33
        0xFF55AAAA, // 34
        0xFF55AAFF, // 35
        0xFF55FF00, // 36
        0xFF55FF55, // 37
        0xFF55FFAA, // 38
        0xFF55FFFF, // 39
        0xFFAA0055, // 40
        0xFFAA00FF, // 41
        0xFFAA5500, // 42
        0xFFAA5555, // 43
        0xFFAA55AA, // 44
        0xFFAA55FF, // 45
        0xFFAAAA55, // 46
        0xFFAAAFFF, // 47
        0xFFAAFF00, // 48
        0xFFAAFF55, // 49
        0xFFAAFFAA, // 50
        0xFFAAFFFF, // 51
        0xFFFF0055, // 52
        0xFFFF00AA, // 53
        0xFFFF5500, // 54
        0xFFFF5555, // 55
        0xFFFF55AA, // 56
        0xFFFF55FF, // 57
        0xFFFFAA00, // 58
        0xFFFFAA55, // 59
        0xFFFFAAAA, // 60
        0xFFFFAAFF, // 61
        0xFFFFFF55, // 62
        0xFFFFFFAA  // 63
    };
    
    private static final int[] colors16 = {
        0xFF000000, 0xFFAA0000, 0xFF00AA00, 0xFFAAAA00,
        0xFF0000AA, 0xFFAA00AA, 0xFF00AAAA, 0xFFAAAAAA,
        0xFF555555, 0xFFFF0000, 0xFF00FF00, 0xFFFFFF00,
        0xFF0000FF, 0xFFFF00FF, 0xFF00FFFF, 0xFFFFFFFF
    };

    public static int getRGBAColorByIndex(int index) {
        return colors64[index];
    }

    public static ColorHsv convertRgbToHsv(int rgb) {
        return ColorConversions.convertRgbToHsv(rgb);
    }

    public static double getColorDistanceHSV(ColorHsv hsv1, ColorHsv hsv2) {
        return Math.sqrt(Math.pow(hsv1.h - hsv2.h, 2) +
                         Math.pow(hsv1.s - hsv2.s, 2) +
                         Math.pow(hsv1.v - hsv2.v, 2));
    }

    public static int findNearestColorHSV(int targetColor, int numcolors) {
        ColorHsv targetHSV = convertRgbToHsv(targetColor);
        double minDistance = Double.MAX_VALUE;
        int nearestColor = 0;

        int[] palette = (numcolors == 16) ? colors16 : colors64;

        for (int color : palette) {
            ColorHsv paletteHSV = convertRgbToHsv(color);
            double distance = getColorDistanceHSV(targetHSV, paletteHSV);
            if (distance < minDistance) {
                minDistance = distance;
                nearestColor = color;
            }
        }

        return nearestColor;
    }

    public static BufferedImage convertToAgonPalette(BufferedImage image, int numcolors, String method) {
        int width = image.getWidth();
        int height = image.getHeight();
        BufferedImage newImg = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);

        for (int x = 0; x < width; x++) {
            for (int y = 0; y < height; y++) {
                int currentPixel = image.getRGB(x, y);
                int nearestColor;

                if (method.equals("HSV")) {
                    nearestColor = findNearestColorHSV(currentPixel, numcolors);
                } else {
                    nearestColor = findNearestColorRGB(currentPixel, numcolors);
                }

                newImg.setRGB(x, y, nearestColor);
            }
        }

        return newImg;
    }

    public static int findNearestColorRGB(int targetColor, int numcolors) {
        int targetRed = (targetColor >> 16) & 0xFF;
        int targetGreen = (targetColor >> 8) & 0xFF;
        int targetBlue = targetColor & 0xFF;
        double minDistance = Double.MAX_VALUE;
        int nearestColor = 0;

        int[] palette = (numcolors == 16) ? colors16 : colors64;

        for (int color : palette) {
            int red = (color >> 16) & 0xFF;
            int green = (color >> 8) & 0xFF;
            int blue = color & 0xFF;
            double distance = Math.sqrt(Math.pow(targetRed - red, 2) +
                                        Math.pow(targetGreen - green, 2) +
                                        Math.pow(targetBlue - blue, 2));
            if (distance < minDistance) {
                minDistance = distance;
                nearestColor = color;
            }
        }

        return nearestColor;
    }

    public static void printHsvTable(int numcolors) {
        int[] palette = (numcolors == 16) ? colors16 : colors64;
        for (int color : palette) {
            ColorHsv hsv = ColorConversions.convertRgbToHsv(color);
            String hsvString = String.format("%.2f,%.2f,%.2f", hsv.h, hsv.s, hsv.v);
            System.out.println(hsvString);
        }
    }

    public static void main(String[] args) {
        int numcolors = 64;  // Change to 16 if you want to output the 16-color palette
        printHsvTable(numcolors);
    }
}
