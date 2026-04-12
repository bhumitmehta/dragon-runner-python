import React from 'react';
import { View, Text, TouchableOpacity, ScrollView } from 'react-native';

const ProductsScreen = ({
  products,
  quantity,
  setQuantity,
  addToCart,
  styles,
  bugMode,
  setCurrentScreen,
  cartItems
}) => (
  <View style={styles.screen}>
    <Text style={styles.title} accessibilityLabel="products-title">Products</Text>
    <View style={styles.quantityRow}>
      <Text>Quantity:</Text>
      <TouchableOpacity
        style={styles.qtyButton}
        onPress={() => setQuantity(Math.max(1, quantity - 1))}
        accessibilityLabel="decrease-quantity"
      >
        <Text style={styles.qtyButtonText}>-</Text>
      </TouchableOpacity>
      <Text style={styles.qtyText} accessibilityLabel="quantity-display">
        {bugMode ? quantity + 1 : quantity}
      </Text>
      <TouchableOpacity
        style={styles.qtyButton}
        onPress={() => setQuantity(quantity + 1)}
        accessibilityLabel="increase-quantity"
      >
        <Text style={styles.qtyButtonText}>+</Text>
      </TouchableOpacity>
    </View>
    <ScrollView style={styles.productList}>
      {products.map((product) => (
        <View key={product.id} style={styles.productCard}>
          <View>
            <Text style={styles.productName} accessibilityLabel={`product-${product.id}-name`}>
              {product.name}
            </Text>
            <Text style={styles.productPrice} accessibilityLabel={`product-${product.id}-price`}>
              ${bugMode ? (product.price * 0.9).toFixed(2) : product.price.toFixed(2)}
            </Text>
          </View>
          <TouchableOpacity
            style={styles.addButton}
            onPress={() => addToCart(product)}
            accessibilityLabel={`add-${product.id}-to-cart`}
          >
            <Text style={styles.addButtonText}>Add</Text>
          </TouchableOpacity>
        </View>
      ))}
    </ScrollView>
    <TouchableOpacity
      style={styles.backButton}
      onPress={() => setCurrentScreen('home')}
      accessibilityLabel="back-to-home"
    >
      <Text style={styles.backButtonText}>← Back</Text>
    </TouchableOpacity>
  </View>
);

export default ProductsScreen;
