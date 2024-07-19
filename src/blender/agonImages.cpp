// Import necessary libraries
#include <opencv2/opencv.hpp>
#include <iostream>
#include <vector>
#include <cmath>
#include <fstream>
#include <stdexcept>

// Define color palettes
std::vector<cv::Vec3b> colors64 = {
    {0, 0, 0}, {170, 0, 0}, {0, 170, 0}, {170, 170, 0}, {0, 0, 170},
    {170, 0, 170}, {0, 170, 170}, {170, 170, 170}, {85, 85, 85},
    {255, 0, 0}, {0, 255, 0}, {255, 255, 0}, {0, 0, 255},
    {255, 0, 255}, {0, 255, 255}, {255, 255, 255}, {0, 0, 85},
    {0, 85, 0}, {0, 85, 85}, {0, 85, 170}, {0, 85, 255},
    {0, 170, 85}, {0, 170, 255}, {0, 255, 85}, {0, 255, 170},
    {85, 0, 0}, {85, 0, 85}, {85, 0, 170}, {85, 0, 255},
    {85, 85, 0}, {85, 85, 170}, {85, 85, 255}, {85, 170, 0},
    {85, 170, 85}, {85, 170, 170}, {85, 170, 255}, {85, 255, 0},
    {85, 255, 85}, {85, 255, 170}, {85, 255, 255}, {170, 0, 85},
    {170, 0, 255}, {170, 85, 0}, {170, 85, 85}, {170, 85, 170},
    {170, 85, 255}, {170, 170, 85}, {170, 170, 255}, {170, 255, 0},
    {170, 255, 85}, {170, 255, 170}, {170, 255, 255}, {255, 0, 85},
    {255, 0, 170}, {255, 85, 0}, {255, 85, 85}, {255, 85, 170},
    {255, 85, 255}, {255, 170, 0}, {255, 170, 85}, {255, 170, 170},
    {255, 170, 255}, {255, 255, 85}, {255, 255, 170}
};

std::vector<cv::Vec3b> colors16 = {
    {0, 0, 0}, {170, 0, 0}, {0, 170, 0}, {170, 170, 0}, {0, 0, 170},
    {170, 0, 170}, {0, 170, 170}, {170, 170, 170}, {85, 85, 85},
    {255, 0, 0}, {0, 255, 0}, {255, 255, 0}, {0, 0, 255},
    {255, 0, 255}, {0, 255, 255}, {255, 255, 255}
};

// Fetch RGBA color by index
cv::Vec4b get_rgba_color_by_index(int index) {
    if (index == -1) {
        return {0, 0, 0, 0};
    }

    if (index < 0 || index >= colors64.size()) {
        throw std::out_of_range("Color index out of range");
    }

    cv::Vec3b rgb = colors64[index];
    return {rgb[0], rgb[1], rgb[2], 255};
}

// Convert RGB to HSV
cv::Vec3f rgb_to_hsv(cv::Vec3b color) {
    cv::Mat rgb(1, 1, CV_8UC3, color);
    cv::Mat hsv;
    cv::cvtColor(rgb, hsv, cv::COLOR_BGR2HSV);
    return hsv.at<cv::Vec3b>(0, 0);
}

// Calculate Euclidean distance in HSV space
double get_color_distance_hsv(cv::Vec3f hsv1, cv::Vec3f hsv2) {
    return std::sqrt(std::pow(hsv1[0] - hsv2[0], 2) + std::pow(hsv1[1] - hsv2[1], 2) + std::pow(hsv1[2] - hsv2[2], 2));
}

// Calculate Euclidean distance in RGB space
double get_color_distance_rgb(cv::Vec3b color1, cv::Vec3b color2) {
    return std::sqrt(std::pow(color1[0] - color2[0], 2) + std::pow(color1[1] - color2[1], 2) + std::pow(color1[2] - color2[2], 2));
}

// Find the nearest color in the palette using RGB
cv::Vec4b find_nearest_color_rgb(cv::Vec4b targetColor, int numcolors) {
    if (targetColor[3] == 0) {
        return {0, 0, 0, 0};
    }
    
    cv::Vec3b targetRGB = {targetColor[0], targetColor[1], targetColor[2]};
    double minDistance = std::numeric_limits<double>::infinity();
    cv::Vec3b nearestColor;

    const auto& colors = (numcolors == 16) ? colors16 : colors64;

    for (const auto& color : colors) {
        double distance = get_color_distance_rgb(targetRGB, color);
        if (distance < minDistance) {
            minDistance = distance;
            nearestColor = color;
        }
    }

    return {nearestColor[0], nearestColor[1], nearestColor[2], 255};
}

// Find the nearest color in the palette using HSV
cv::Vec4b find_nearest_color_hsv(cv::Vec4b targetColor, int numcolors) {
    if (targetColor[3] == 0) {
        return {0, 0, 0, 0};
    }

    cv::Vec3f targetHSV = rgb_to_hsv({targetColor[0], targetColor[1], targetColor[2]});
    double minDistance = std::numeric_limits<double>::infinity();
    cv::Vec3b nearestColor;

    const auto& colors = (numcolors == 16) ? colors16 : colors64;

    for (const auto& color : colors) {
        cv::Vec3f paletteHSV = rgb_to_hsv(color);
        double distance = get_color_distance_hsv(targetHSV, paletteHSV);
        if (distance < minDistance) {
            minDistance = distance;
            nearestColor = color;
        }
    }

    return {nearestColor[0], nearestColor[1], nearestColor[2], 255};
}

// Convert image to custom palette
cv::Mat convert_to_agon_palette(const cv::Mat& image, int numcolors, const std::string& method, cv::Vec3b transparent_color = {-1, -1, -1}) {
    cv::Mat new_img(image.size(), CV_8UC4);

    for (int y = 0; y < image.rows; ++y) {
        for (int x = 0; x < image.cols; ++x) {
            cv::Vec4b current_pixel = image.at<cv::Vec4b>(y, x);

            cv::Vec4b nearest_color;
            if (transparent_color != cv::Vec3b{-1, -1, -1} && cv::Vec3b(current_pixel[0], current_pixel[1], current_pixel[2]) == transparent_color) {
                nearest_color = {0, 0, 0, 0};
            } else {
                if (method == "RGB") {
                    nearest_color = find_nearest_color_rgb(current_pixel, numcolors);
                } else if (method == "HSV") {
                    nearest_color = find_nearest_color_hsv(current_pixel, numcolors);
                } else {
                    throw std::invalid_argument("Invalid method. Use 'RGB' or 'HSV'.");
                }
            }
            new_img.at<cv::Vec4b>(y, x) = nearest_color;
        }
    }

    return new_img;
}

// Save RGBA image to file
void img_to_rgba8(const cv::Mat& image, const std::string& filepath) {
    std::ofstream file(filepath, std::ios::binary);
    if (!file.is_open()) {
        throw std::runtime_error("Could not open file for writing");
    }

    for (int y = 0; y < image.rows; ++y) {
        for (int x = 0; x < image.cols; ++x) {
            cv::Vec4b pixel = image.at<cv::Vec4b>(y, x);
            file.write(reinterpret_cast<char*>(&pixel), 4);
        }
    }

    file.close();
}

// Quantize to 2-bit
uint8_t quantize_to_2bit(uint8_t value) {
    if (value < 85 / 2) return 0b00;
    if (value < (85 + 170) / 2) return 0b01;
    if (value < (170 + 255) / 2) return 0b10;
    return 0b11;
}

// Save image to 2-bit format
void img_to_rgba2(const cv::Mat& image, const std::string& filepath) {
    std::ofstream file(filepath, std::ios::binary);
    if (!file.is_open()) {
        throw std::runtime_error("Could not open file for writing");
    }

    for (int y = 0; y < image.rows; ++y) {
        for (int x = 0; x < image.cols; ++x) {
            cv::Vec4b pixel = image.at<cv::Vec4b>(y, x);
            uint8_t a_q = quantize_to_2bit(pixel[3]);
            uint8_t b_q = quantize_to_2bit(pixel[0]);
            uint8_t g_q = quantize_to_2bit(pixel[1]);
            uint8_t r_q = quantize_to_2bit(pixel[2]);
            uint8_t combined = (a_q << 6) | (b_q << 4) | (g_q << 2) | r_q;
            file.write(reinterpret_cast<char*>(&combined), 1);
        }
    }

    file.close();
}

// Load RGBA8 binary file into image
cv::Mat rgba8_to_img(const std::string& src_file_path, int dim_x, int dim_y) {
    std::ifstream file(src_file_path, std::ios::binary);
    if (!file.is_open()) {
        throw std::runtime_error("Could not open file for reading");
    }

    std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    cv::Mat image(dim_y, dim_x, CV_8UC4, data.data());

    return image.clone();
}

// Decode 2-bit pixel
std::array<uint8_t, 4> decode_pixel(uint8_t pixel) {
    uint8_t a = (pixel >> 6) & 0b11;
    uint8_t b = (pixel >> 4) & 0b11;
    uint8_t g = (pixel >> 2) & 0b11;
    uint8_t r = pixel & 0b11;
    std::array<uint8_t, 4> mapping = {0, 85, 170, 255};
    return {mapping[r], mapping[g], mapping[b], mapping[a]};
}

// Load RGBA2 binary file into image
cv::Mat rgba2_to_img(const std::string& src_file_path, int dim_x, int dim_y) {
    std::ifstream file(src_file_path, std::ios::binary);
    if (!file.is_open()) {
        throw std::runtime_error("Could not open file for reading");
    }

    std::vector<uint8_t> binary_data((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    std::vector<uint8_t> pixel_data;

    for (auto byte : binary_data) {
        auto decoded_pixels = decode_pixel(byte);
        pixel_data.insert(pixel_data.end(), decoded_pixels.begin(), decoded_pixels.end());
    }

    cv::Mat image(dim_y, dim_x, CV_8UC4, pixel_data.data());
    return image.clone();
}

int main() {
    try {
        cv::Mat image = cv::imread("input.png", cv::IMREAD_UNCHANGED);
        if (image.empty()) {
            throw std::runtime_error("Could not open or find the image");
        }

        cv::Mat new_img = convert_to_agon_palette(image, 16, "RGB", {0, 0, 0});
        img_to_rgba8(new_img, "output.rgba8");
        img_to_rgba2(new_img, "output.rgba2");

        cv::Mat rgba8_img = rgba8_to_img("output.rgba8", image.cols, image.rows);
        cv::Mat rgba2_img = rgba2_to_img("output.rgba2", image.cols, image.rows);

        cv::imwrite("output_rgba8.png", rgba8_img);
        cv::imwrite("output_rgba2.png", rgba2_img);
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
    }

    return 0;
}
