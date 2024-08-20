import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;
import java.io.IOException;

public class EquirectangularVisualizer extends JPanel implements KeyListener {
    private BufferedImage texture;
    private double yaw = 0.0;
    private double pitch = 0.0;
    private double uPhase = 0.0;  // New phase angle control
    private int screenWidth = 640;
    private int screenHeight = 480;

    public EquirectangularVisualizer(String texturePath) {
        try {
            texture = ImageIO.read(new File(texturePath));
        } catch (IOException e) {
            e.printStackTrace();
        }
        setPreferredSize(new Dimension(screenWidth, screenHeight));
        addKeyListener(this);
        setFocusable(true);
    }

    @Override
    protected void paintComponent(Graphics g) {
        super.paintComponent(g);

        for (int y = 0; y < screenHeight; y++) {
            for (int x = 0; x < screenWidth; x++) {
                double nx = (x / (double) screenWidth) * 2 - 1;
                double ny = (y / (double) screenHeight) * 2 - 1;

                double phi = Math.atan2(nx, 1);
                double theta = Math.atan2(ny, 1);

                double adjYaw = yaw + phi + uPhase;  // Include uPhase adjustment
                double adjPitch = pitch + theta;

                adjPitch = Math.max(Math.min(adjPitch, Math.PI / 2), -Math.PI / 2);

                double u = ((adjYaw + Math.PI / 2) + Math.PI) / (2 * Math.PI);
                double v = (adjPitch + Math.PI / 2) / Math.PI;

                int texX = (int) (u * texture.getWidth()) % texture.getWidth();
                int texY = (int) (v * texture.getHeight()) % texture.getHeight();

                int color = texture.getRGB(texX, texY);
                g.setColor(new Color(color));
                g.drawLine(x, y, x, y);
            }
        }
    }

    @Override
    public void keyPressed(KeyEvent e) {
        if (e.getKeyCode() == KeyEvent.VK_LEFT) {
            yaw -= Math.toRadians(5);
        } else if (e.getKeyCode() == KeyEvent.VK_RIGHT) {
            yaw += Math.toRadians(5);
        } else if (e.getKeyCode() == KeyEvent.VK_UP) {
            pitch += Math.toRadians(5);
        } else if (e.getKeyCode() == KeyEvent.VK_DOWN) {
            pitch -= Math.toRadians(5);
        } else if (e.getKeyCode() == KeyEvent.VK_A) {  // Adjust uPhase to the left
            uPhase -= Math.toRadians(5);
        } else if (e.getKeyCode() == KeyEvent.VK_D) {  // Adjust uPhase to the right
            uPhase += Math.toRadians(5);
        }
        yaw = yaw % (2 * Math.PI);
        repaint();
    }

    @Override
    public void keyReleased(KeyEvent e) {}

    @Override
    public void keyTyped(KeyEvent e) {}

    public static void main(String[] args) {
        JFrame frame = new JFrame("Equirectangular Visualizer");
        EquirectangularVisualizer visualizer = new EquirectangularVisualizer("src/blender/equirectangular.png");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.add(visualizer);
        frame.pack();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);

        frame.addWindowListener(new WindowAdapter() {
            @Override
            public void windowClosing(WindowEvent e) {
                System.exit(0);
            }
        });
    }
}
