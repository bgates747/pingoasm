import java.util.Comparator;

import java.awt.image.BufferedImage;
import java.util.List;
import java.util.ArrayList;
import java.util.Collections;


public class AgonColors2 {

    private static final int[] colors64 = {
        0xFF000000, 0xFFAA0000, 0xFF00AA00, 0xFFAAAA00, 0xFF0000AA,
        0xFFAA00AA, 0xFF00AAAA, 0xFFAAAAAA, 0xFF555555, 0xFFFF0000,
        0xFF00FF00, 0xFFFFFF00, 0xFF0000FF, 0xFFFF00FF, 0xFF00FFFF,
        0xFFFFFFFF, 0xFF000055, 0xFF005500, 0xFF005555, 0xFF0055AA,
        0xFF0055FF, 0xFF00AA55, 0xFF00AAFF, 0xFF00FF55, 0xFF00FFAA,
        0xFF550000, 0xFF550055, 0xFF5500AA, 0xFF5500FF, 0xFF555500,
        0xFF5555AA, 0xFF5555FF, 0xFF55AA00, 0xFF55AA55, 0xFF55AAAA,
        0xFF55AAFF, 0xFF55FF00, 0xFF55FF55, 0xFF55FFAA, 0xFF55FFFF,
        0xFFAA0055, 0xFFAA00FF, 0xFFAA5500, 0xFFAA5555, 0xFFAA55AA,
        0xFFAA55FF, 0xFFAAAA55, 0xFFAAAFFF, 0xFFAAFF00, 0xFFAAFF55,
        0xFFAAFFAA, 0xFFAAFFFF, 0xFFFF0055, 0xFFFF00AA, 0xFFFF5500,
        0xFFFF5555, 0xFFFF55AA, 0xFFFF55FF, 0xFFFFAA00, 0xFFFFAA55,
        0xFFFFAAAA, 0xFFFFAAFF, 0xFFFFFF55, 0xFFFFFFAA
    };

    private static final int[] colors16 = {
        0xFF000000, 0xFFAA0000, 0xFF00AA00, 0xFFAAAA00,
        0xFF0000AA, 0xFFAA00AA, 0xFF00AAAA, 0xFFAAAAAA,
        0xFF555555, 0xFFFF0000, 0xFF00FF00, 0xFFFFFF00,
        0xFF0000FF, 0xFFFF00FF, 0xFF00FFFF, 0xFFFFFFFF
    };

    public static BufferedImage convertToAgonPalette(BufferedImage image, int numcolors) {
        int width = image.getWidth();
        int height = image.getHeight();
        BufferedImage newImg = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);

        List<PixelDistance> distances = new ArrayList<>();
        int[][] nearestColorMatrix = new int[width][height];

        // Step 1: Calculate RGB distances
        for (int x = 0; x < width; x++) {
            for (int y = 0; y < height; y++) {
                int currentPixel = image.getRGB(x, y);
                int nearestColor = findNearestColorRGB(currentPixel, numcolors);
                nearestColorMatrix[x][y] = nearestColor;

                double distance = getRgbDistance(currentPixel, nearestColor);
                distances.add(new PixelDistance(x, y, distance));
            }
        }

        // Step 2: Sort pixels by distance and select top 5%
        Collections.sort(distances, Comparator.comparingDouble(pd -> pd.distance));
        int topFivePercent = (int) (distances.size() * 0.20);
        List<PixelDistance> topMatches = distances.subList(0, topFivePercent);

        // Assign nearest color to top 5%
        for (PixelDistance pd : topMatches) {
            newImg.setRGB(pd.x, pd.y, nearestColorMatrix[pd.x][pd.y]);
        }

        // Step 3: Nearest neighbor interpolation for non-top matches
        for (int x = 0; x < width; x++) {
            for (int y = 0; y < height; y++) {
                if (!topMatches.contains(new PixelDistance(x, y, 0))) {
                    int nearestMatchColor = findNearestTopMatch(x, y, topMatches, nearestColorMatrix);
                    newImg.setRGB(x, y, nearestMatchColor);
                }
            }
        }

        return newImg;
    }

    private static double getRgbDistance(int color1, int color2) {
        int r1 = (color1 >> 16) & 0xFF;
        int g1 = (color1 >> 8) & 0xFF;
        int b1 = color1 & 0xFF;

        int r2 = (color2 >> 16) & 0xFF;
        int g2 = (color2 >> 8) & 0xFF;
        int b2 = color2 & 0xFF;

        return Math.sqrt(Math.pow(r1 - r2, 2) +
                         Math.pow(g1 - g2, 2) +
                         Math.pow(b1 - b2, 2));
    }

    private static int findNearestTopMatch(int x, int y, List<PixelDistance> topMatches, int[][] nearestColorMatrix) {
        int nearestDistance = Integer.MAX_VALUE;
        int nearestColor = 0;

        for (PixelDistance pd : topMatches) {
            int matchX = pd.x;
            int matchY = pd.y;
            int distance = Math.abs(x - matchX) + Math.abs(y - matchY); // Manhattan distance

            if (distance < nearestDistance) {
                nearestDistance = distance;
                nearestColor = nearestColorMatrix[matchX][matchY];
            }
        }

        return nearestColor;
    }

    private static class PixelDistance {
        int x, y;
        double distance;

        PixelDistance(int x, int y, double distance) {
            this.x = x;
            this.y = y;
            this.distance = distance;
        }

        @Override
        public boolean equals(Object obj) {
            if (this == obj) return true;
            if (obj == null || getClass() != obj.getClass()) return false;
            PixelDistance that = (PixelDistance) obj;
            return x == that.x && y == that.y;
        }

        @Override
        public int hashCode() {
            return 31 * x + y;
        }
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
}
