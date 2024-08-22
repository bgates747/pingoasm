import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import javax.imageio.ImageIO;

public class AgonColorPreview2 {

    public static void main(String[] args) {
        // Set your parameters here directly
        String filepath = "src/blender/koak.png";  // Replace with your image path
        int numcolors = 64;  // Set to 16 or 64

        try {
            BufferedImage originalImage = ImageIO.read(new File(filepath));
            BufferedImage convertedImage = AgonColors2.convertToAgonPalette(originalImage, numcolors);

            // Display the original and converted images in a JFrame
            JFrame frame = new JFrame("AgonColorPreview");
            frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
            frame.setLayout(new GridLayout(1, 2));

            // Original image panel
            JLabel originalLabel = new JLabel(new ImageIcon(originalImage));
            frame.add(originalLabel);

            // Converted image panel
            JLabel convertedLabel = new JLabel(new ImageIcon(convertedImage));
            frame.add(convertedLabel);

            frame.pack();
            frame.setVisible(true);

            // Save the converted image
            File file = new File(filepath);
            String baseName = file.getName().substring(0, file.getName().lastIndexOf('.'));
            String extension = file.getName().substring(file.getName().lastIndexOf('.'));
            String newFilename = file.getParent() + File.separator + baseName + ".jv2." + numcolors + extension;
            ImageIO.write(convertedImage, extension.replace(".", ""), new File(newFilename));
            System.out.println("Converted image saved as " + newFilename);

        } catch (IOException e) {
            System.out.println("Error: Unable to read or save the image file.");
            e.printStackTrace();
        }
    }
}
